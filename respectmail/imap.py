from imapclient import IMAPClient, SEEN
import email
import warnings
from getpass import getpass

INBOX = 0
SENT = 1
JUNK = 2
REQUESTS = 3
FYI = 4
CLOSED = 5
REQUESTSTRIAGE = 6
FYITRIAGE = 7
CLOSEDTRIAGE = 8
JUNKTRIAGE = 9
BLACKLIST = 10
BLACKLISTTRIAGE = 11

class IMAPServer(object):
    def __init__(self, host, user, password=None, ssl=True, serverID=1,
                 mboxlist=('INBOX', 'Sent', 'Junk', 'Requests', 'FYI',
                           'Closed', 'Requests', 'FYI',
                           'Closed', 'JunkTriage', 'Blacklist',
                           'StrangersINBOX',), 
                 **kwargs):
        'connect to imap server'
        self.server = IMAPClient(host, ssl=ssl, **kwargs)
        if password is None:
            password = getpass('Enter password for %s on %s:' %
                               (user, host))
        self.server.login(user, password)
        self.mboxlist = mboxlist
        self.serverID = serverID
        self.host = host
        self.user = user

    def create_mailboxes(self):
        'ensure that our standard mailboxes exist'
        folders = frozenset([t[2] for t in self.server.list_folders()])
        for mbox in self.mboxlist:
            if mbox not in folders:
                response = self.server.create_folder(mbox)
                print 'Created', mbox, response

    def get_updates(self, triageDB, expunge=True):
        'get INBOX, SENT headers; save to triageDB'
        msgLists = []
        msgHeaders = get_headers(self.server, self.mboxlist[INBOX])
        triageDB.save_headers(msgHeaders, self.mboxlist[INBOX],
                              serverID=self.serverID, verdict=INBOX)
        msgLists.append(msgHeaders)
        msgHeaders = get_headers(self.server, self.mboxlist[SENT])
        triageDB.save_headers(msgHeaders, self.mboxlist[SENT], fromMe=True,
                              serverID=self.serverID, verdict=SENT)
        msgLists.append(msgHeaders)
        self.msgLists = msgLists
        # update verdicts based on last round of triage by user
        msgHeaders = get_headers(self.server, self.mboxlist[REQUESTS])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[REQUESTS], REQUESTS)
        msgHeaders = get_headers(self.server, self.mboxlist[FYI])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[FYI], FYI)
        msgHeaders = get_headers(self.server, self.mboxlist[CLOSED])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[CLOSED], CLOSED)
        self.get_blacklist_updates(self.mboxlist[BLACKLIST], triageDB, expunge)
        self.get_blacklist_updates(self.mboxlist[BLACKLISTTRIAGE], triageDB,
                                   expunge)
    def get_blacklist_updates(self, mbox, triageDB, expunge=True):
        'update blacklist verdicts based on user actions, and clear mbox'
        msgHeaders = get_headers(self.server, mbox)
        triageDB.save_verdicts(msgHeaders, self.mboxlist[BLACKLIST], BLACKLIST)
        triageDB.blacklist(msgHeaders)
        self.server.delete_messages([t[0] for t in msgHeaders])
        if expunge:
            self.server.expunge()

    def triage(self, triageDB):
        'triage inbox to request, fyi, junk, blacklist mboxes'
        requestAddrs, fyiAddrs, junkAddrs, blackAddrs = triageDB.get_triage()
        fromBox = self.mboxlist[INBOX]
        msgHeaders = self.msgLists[INBOX]
        msgSet = set([t[0] for t in msgHeaders])
        answered = [t for t in msgHeaders if '\\Answered' in t[1]._imapFlags]
        self._do_triage(None, answered, triageDB, fromBox, 
                        self.mboxlist[CLOSEDTRIAGE])
        msgSet -= frozenset([t[0] for t in answered])
        requests = [t for t in msgHeaders if t[0] in msgSet and 
                    triageDB.msgThread.get(t[1].uid, None) 
                    in triageDB.myThreads]
        self._do_triage(None, requests, triageDB, fromBox, 
                        self.mboxlist[REQUESTSTRIAGE])
        msgSet -= frozenset([t[0] for t in requests])
        requests = self._do_triage(requestAddrs,
                                   [t for t in msgHeaders if t[0] in msgSet],
                                   triageDB,
                                   fromBox, self.mboxlist[REQUESTSTRIAGE])
        msgSet -= frozenset([t[0] for t in requests])
        fyi = self._do_triage(fyiAddrs,
                              [t for t in msgHeaders if t[0] in msgSet],
                              triageDB,
                              fromBox, self.mboxlist[FYITRIAGE])
        msgSet -= frozenset([t[0] for t in fyi])
        black = self._do_triage(blackAddrs,
                                [t for t in msgHeaders if t[0] in msgSet],
                                triageDB,
                                fromBox, self.mboxlist[BLACKLIST])
        msgSet -= frozenset([t[0] for t in black])
        junk = self._do_triage(junkAddrs,
                              [t for t in msgHeaders if t[0] in msgSet],
                               triageDB,
                              fromBox, self.mboxlist[JUNKTRIAGE])
        msgSet -= frozenset([t[0] for t in junk])
        # move messages from strangers into BLACKLISTTRIAGE mbox
        strangers = self._do_triage(None, 
                                    [t for t in msgHeaders if t[0] in msgSet],
                                    triageDB,
                                    fromBox, self.mboxlist[BLACKLISTTRIAGE])

    def _do_triage(self, addrs, msgHeaders, triageDB, fromBox, toBox):
        'move msgs from the specified addrs to toBox'
        if addrs:
            msgHeaders = filter_mail(msgHeaders, addrs)
        if not msgHeaders:
            return ()
        print 'Triaging %d messages to %s...' % (len(msgHeaders), toBox)
        move_messages(self.server, msgHeaders, fromBox, toBox)
        triageDB.save_moves(msgHeaders, toBox)
        return msgHeaders

    def _rescue_update(self, triageDB):
        'recreate last update state (without any db change), ready for triage'
        msgHeaders = get_headers(self.server, self.mboxlist[INBOX])
        l = []
        for j,msg in msgHeaders:
            triageDB.cursor.execute('select id from messages where msgid=?',
                                    (msg['message-id'],))
            t = triageDB.cursor.fetchone()
            if t is not None:
                msg.uid = t[0]
                l.append((j,msg))
        self.msgLists = [l]
        
def get_from(msg):
    origin = email.utils.getaddresses(msg.get_all('from', []))
    return frozenset([t[1].lower() for t in origin])

def filter_mail(msgHeaders, addrs):
    return [t for t in msgHeaders if not get_from(t[1]).isdisjoint(addrs)]


def get_headers(server, mailbox='INBOX', maxreq=200, data='BODY[HEADER]'):
    'retrieve headers for a mailbox, return as [(serverID,message_obj),]'
    server.select_folder(mailbox)
    unseen = server.search('UNSEEN') # preserve UNSEEN state
    msgList = server.search(['NOT DELETED'])
    msgHeaders = []
    for i in range(0, len(msgList), maxreq):
        msgDict = server.fetch(msgList[i:i + maxreq], ['FLAGS', data])
        for j,m in msgDict.iteritems():
            try:
                msg = email.message_from_string(m[data])
            except UnicodeEncodeError:
                warnings.warn('ignoring message headers due to UnicodeEncodeError')
            else:
                msg._imapFlags = m['FLAGS']
                msgHeaders.append((j,msg))
    server.remove_flags(unseen, [SEEN]) # reset back to unseen state
    return msgHeaders



def move_messages(server, msgHeaders, fromBox='INBOX', toBox='Junk',
                  expunge=True):
    'copy the specified messages to toBox, then delete from fromBox'
    server.select_folder(fromBox)
    msgList = [t[0] for t in msgHeaders]
    server.copy(msgList, toBox)
    server.delete_messages(msgList)
    if expunge:
        server.expunge()

def ensure_folder(server, foldername):
    'create folder if it does not already exist and return response string'
    for flags, delimiter, name in server.list_folders():
        if name == foldername:
            return False
    return server.create_folder(foldername)

#md = mailbox.Maildir('maildirtest')
#    localID = md.add(msg)
