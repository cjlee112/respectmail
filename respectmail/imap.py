from imapclient import IMAPClient, SEEN
import email
from email.feedparser import FeedParser
from email.message import Message
import warnings
from getpass import getpass
import socket
import imaplib

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
        self.server = RobustClient(host, user, password, ssl=ssl, **kwargs)
        self.mboxlist = mboxlist
        self.msgLists = {}
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
        msgHeaders = get_headers(self.server, self.mboxlist[INBOX])
        triageDB.save_headers(msgHeaders, self.mboxlist[INBOX],
                              serverID=self.serverID)
        self.msgLists[INBOX] = msgHeaders
        msgHeaders = get_headers(self.server, self.mboxlist[SENT])
        triageDB.save_headers(msgHeaders, self.mboxlist[SENT], 
                              fromMe=True, from_me_f=None,
                              serverID=self.serverID, verdict=SENT)
        self.msgLists[SENT] = msgHeaders
        # update verdicts based on last round of triage by user
        msgHeaders = get_headers(self.server, self.mboxlist[REQUESTS])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[REQUESTS], REQUESTS,
                               serverID=self.serverID)
        self.msgLists[REQUESTS] = msgHeaders
        msgHeaders = get_headers(self.server, self.mboxlist[FYI])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[FYI], FYI,
                               serverID=self.serverID)
        self.msgLists[FYI] = msgHeaders
        msgHeaders = get_headers(self.server, self.mboxlist[CLOSED])
        triageDB.save_verdicts(msgHeaders, self.mboxlist[CLOSED], CLOSED,
                               overwrite=False, serverID=self.serverID)
        self.purge_blacklist(triageDB, expunge)

    def purge_blacklist(self, triageDB, expunge=True):
        '''treat all messages in BLACKLIST/TRIAGE as blacklisted:
        save verdicts to triageDB, and expunge from imap server'''
        self.get_blacklist_updates(self.mboxlist[BLACKLIST], triageDB, expunge)
        self.get_blacklist_updates(self.mboxlist[BLACKLISTTRIAGE], triageDB,
                                   expunge)
    def get_blacklist_updates(self, mbox, triageDB, expunge=True):
        'update blacklist verdicts based on user actions, and clear mbox'
        msgHeaders = get_headers(self.server, mbox)
        triageDB.save_verdicts(msgHeaders, self.mboxlist[BLACKLIST], BLACKLIST,
                               serverID=self.serverID)
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
        answered = [t for t in msgHeaders 
                    if '\\Answered' in t[1]._imapFlags or t[1].fromMe]
        self._do_triage(answered, triageDB, fromBox, 
                        self.mboxlist[CLOSEDTRIAGE])
        msgSet -= frozenset([t[0] for t in answered])
        requests = [t for t in msgHeaders if t[0] in msgSet and 
                    triageDB.msgThread.get(t[1].uid, None) 
                    in triageDB.myThreads]
        self._do_triage(requests, triageDB, fromBox, 
                        self.mboxlist[REQUESTSTRIAGE])
        msgSet -= frozenset([t[0] for t in requests])
        requests = self._do_triage([t for t in msgHeaders if t[0] in msgSet],
                                   triageDB, fromBox, 
                                   self.mboxlist[REQUESTSTRIAGE], requestAddrs)
        msgSet -= frozenset([t[0] for t in requests])
        fyi = self._do_triage([t for t in msgHeaders if t[0] in msgSet],
                              triageDB, fromBox, 
                              self.mboxlist[FYITRIAGE], fyiAddrs)
        msgSet -= frozenset([t[0] for t in fyi])
        black = self._do_triage([t for t in msgHeaders if t[0] in msgSet],
                                triageDB, fromBox, 
                                self.mboxlist[BLACKLIST], blackAddrs)
        msgSet -= frozenset([t[0] for t in black])
        junk = self._do_triage([t for t in msgHeaders if t[0] in msgSet],
                               triageDB, fromBox, 
                               self.mboxlist[JUNKTRIAGE], junkAddrs)
        msgSet -= frozenset([t[0] for t in junk])
        # move messages from strangers into BLACKLISTTRIAGE mbox
        strangers = self._do_triage([t for t in msgHeaders if t[0] in msgSet],
                                    triageDB,
                                    fromBox, self.mboxlist[BLACKLISTTRIAGE])
        self.close_answered(triageDB)

    def close_answered(self, triageDB):
        'move answered messages to CLOSED mailbox and update db'
        answered = triageDB.get_answered_messages()
        msgHeaders = filter_message_ids(self.msgLists[REQUESTS], answered)
        self._do_triage(msgHeaders, triageDB, self.mboxlist[REQUESTS], 
                        self.mboxlist[CLOSED])
        msgHeaders = filter_message_ids(self.msgLists[FYI], answered)
        self._do_triage(msgHeaders, triageDB, self.mboxlist[FYI], 
                        self.mboxlist[CLOSED])

    def _do_triage(self, msgHeaders, triageDB, fromBox, toBox, addrs=None):
        'move msgs (subset from addrs if specified) to toBox'
        if addrs:
            msgHeaders = filter_message_addrs(msgHeaders, addrs)
        if not msgHeaders:
            return ()
        print 'Triaging %d messages to %s...' % (len(msgHeaders), toBox)
        move_messages(self.server, msgHeaders, fromBox, toBox)
        triageDB.save_moves(msgHeaders, toBox)
        return msgHeaders

    def _rescue_update(self, triageDB):
        'recreate last update state (without any db change), ready for triage'
        if not hasattr(triageDB, 'myThreads'):
            triageDB._load_threads()
        msgHeaders = get_headers(self.server, self.mboxlist[INBOX])
        l = []
        for j,msg in msgHeaders:
            triageDB.cursor.execute('select id from messages where msgid=?',
                                    (msg['message-id'],))
            t = triageDB.cursor.fetchone()
            if t is not None:
                msg.uid = t[0]
                l.append((j,msg))
        self.msgLists[INBOX] = l
        msgHeaders = get_headers(self.server, self.mboxlist[REQUESTS])
        self.msgLists[REQUESTS] = msgHeaders
        msgHeaders = get_headers(self.server, self.mboxlist[FYI])
        self.msgLists[FYI] = msgHeaders

    def get_messages(self, mbox='Drafts'):
        'get full-text email message objects'
        return get_headers(self.server, mbox, data='RFC822', 
                           preserveState=False)
        
def get_from(msg):
    origin = email.utils.getaddresses(msg.get_all('from', []))
    return frozenset([t[1].lower() for t in origin])

def filter_message_addrs(msgHeaders, addrs):
    'filter messages to those from specified addrs'
    return [t for t in msgHeaders if not get_from(t[1]).isdisjoint(addrs)]

def filter_message_ids(msgHeaders, msgDict):
    'filter messages in msgHeaders by msgIDs in msgDict'
    l = []
    for serverMsg,m in msgHeaders:
        try:
            msgID = m['message-id']
            m.uid = msgDict[msgID]
        except KeyError:
            continue
        else:
            l.append((serverMsg, m))
    return l

def message_from_string_safe(text):
    'handle failure by email standard library by bypassing StringIO blowup'
    try: # use the standard library by default
        return email.message_from_string(text)
    except UnicodeEncodeError: # code copied from email.parser.Parser.parse()
        feedparser = FeedParser(Message)
        feedparser._set_headersonly()
        feedparser.feed(text)
        return feedparser.close()

def get_headers(server, mailbox='INBOX', maxreq=200, data='BODY[HEADER]',
                preserveState=True):
    'retrieve headers for a mailbox, return as [(serverID,message_obj),]'
    server.select_folder(mailbox)
    if preserveState:
        unseen = server.search('UNSEEN') # preserve UNSEEN state
    msgList = server.search(['NOT DELETED'])
    msgHeaders = []
    for i in range(0, len(msgList), maxreq):
        msgDict = server.fetch(msgList[i:i + maxreq], ['FLAGS', data])
        for j,m in msgDict.iteritems():
            msg = message_from_string_safe(m[data])
            msg._imapFlags = m['FLAGS']
            msgHeaders.append((j,msg))
    if preserveState:
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

class RobustClient(object):
    'IMAP connection that auto-retries after socket.error'
    def __init__(self, host, user, password=None, immediateLogin=False,
                 *args, **kwargs):
        self._host = host
        self._user = user
        if password is None:
            password = getpass('Enter password for %s on %s:' %
                               (user, host))
        self._password = password
        self._args = args
        self._kwargs = kwargs
        if immediateLogin:
            self._connect()
    def _connect(self):
        'login to IMAP server'
        self._server = IMAPClient(self._host, *self._args, **self._kwargs)
        self._server.login(self._user, self._password)
    def _disconnect(self):
        '''drop IMAPClient connection, e.g. to prevent socket timeout
        (any method call will automatically reconnect)'''
        self._server.logout()
        del self._server
    def _robust_call(self, funcName, *args, **kwargs):
        'perform IMAPClient call, restoring server connection if necessary'
        topLevel = ('list_folders', 'create_folder', 'select_folder')
        if not hasattr(self, '_server'): # connect just-in-time
            self._connect()
        while True:
            func = getattr(self._server, funcName)
            try:
                return func(*args, **kwargs)
            except (socket.error, imaplib.IMAP4.abort):
                print 'socket error for %s.  Retrying...' % self._host
                while True:
                    try:
                        self._connect()
                    except:
                        raw_input('Reconnect failed. Check network and hit enter to retry...')
                    else:
                        break
                if funcName not in topLevel: # must reconnect current folder
                    self._server.select_folder(self._folder)
    # proxy the IMAPClient methods...
    def select_folder(self, folder, *args, **kwargs):
        'remember folder name in case we need to restore connection'
        response = self._robust_call('select_folder', folder, *args, **kwargs)
        self._folder = folder
        return response
    list_folders = lambda self, *args, **kwargs: \
      self._robust_call('list_folders', *args, **kwargs)
    create_folder = lambda self, *args, **kwargs: \
      self._robust_call('create_folder', *args, **kwargs)
    delete_messages = lambda self, *args, **kwargs: \
      self._robust_call('delete_messages', *args, **kwargs)
    expunge = lambda self, *args, **kwargs: \
      self._robust_call('expunge', *args, **kwargs)
    search = lambda self, *args, **kwargs: \
      self._robust_call('search', *args, **kwargs)
    fetch = lambda self, *args, **kwargs: \
      self._robust_call('fetch', *args, **kwargs)
    remove_flags = lambda self, *args, **kwargs: \
      self._robust_call('remove_flags', *args, **kwargs)
    copy = lambda self, *args, **kwargs: \
      self._robust_call('copy', *args, **kwargs)

#md = mailbox.Maildir('maildirtest')
#    localID = md.add(msg)
