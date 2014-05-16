import mailbox
import os
import email
import sqlite3
import json
import time
import datetime
from math import log, exp, isnan
from scipy import special, stats
import numpy
#import warnings


class TriageDB(object):
    def __init__(self, dbfile='maildir.db', createTables=False, myAddrs=()):
        self.conn = db_connect(dbfile)
        self.cursor = self.conn.cursor()
        if createTables:
            create_messages_table(self.cursor)
            create_addrs_table(self.cursor)
            create_addrs_table(self.cursor, 'junkaddrs')
            create_addrs_table(self.cursor, 'verdictaddrs')
            save_myaddrs_table(self.cursor, myAddrs)
            save_myaddrs_table(self.cursor, tableName='notjunk')
            save_myaddrs_table(self.cursor, tableName='vip')
            save_myaddrs_table(self.cursor, tableName='blacklist')
            self.conn.commit()
        myAddrs = set()
        self.cursor.execute('select * from myaddrs')
        for t in self.cursor.fetchall():
            myAddrs.add(t[0].lower())
        self.myAddrs = myAddrs

    def save_headers(self, msgHeaders, mailbox='INBOX', fromMe=False, 
                     serverID=1, **kwargs):
        'save message headers to db as NEW messages'
        if mailbox == 'Sent':
            fromMe = True
        if fromMe: # override from_me_f()
            kwargs['from_me_f'] = None
        save_messages(self.cursor, msgHeaders, fromMe=fromMe, mboxName=mailbox,
                      myAddrs=self.myAddrs, serverID=serverID, **kwargs)
        self.conn.commit()

    def save_verdicts(self, msgHeaders, mailbox, verdict):
        'user has triaged messages to mailbox, so record that verdict'
        save_verdicts(self.cursor, msgHeaders, mailbox, verdict)
        self.conn.commit()

    def update_threads(self, goodVerdicts):
        'extend thread analysis to NEW messages and verdicts'
        self.threadMsgs, self.msgThread, self.myThreads, self.low, self.high = \
            reanalyze_threads(self.cursor)
        self.conn.commit()
        self.verdicts = get_sender_verdicts(self.cursor, goodVerdicts)
        create_addrs_table(self.cursor, 'verdictaddrs')
        save_addrs(self.cursor, self.verdicts, 'verdictaddrs')
        self.conn.commit()

    def get_triage(self, requestP=0.05, junkP=0.05, fyiReplies=1):
        'get triage of email addresses into likely requests, fyi, junk sets'
        if not hasattr(self, 'high'):
            self.cursor.execute('select pval, nrelevant, ntotal, email from addrs')
            self.high = self.cursor.fetchall()
        requestAddrs = frozenset([t[3] for t in self.high if t[0] < requestP])
        fyiAddrs = frozenset([t[3] for t in self.high if t[1] >= fyiReplies])
        junkAddrs = get_junkaddrs(self.cursor, junkP)
        blackAddrs = get_blacklist(self.cursor)
        return requestAddrs, fyiAddrs, junkAddrs, blackAddrs

    def save_moves(self, msgHeaders, toBox='Junk', tableName='messages'):
        'record mailbox move for the set of messages'
        for j,msg in msgHeaders:
            self.cursor.execute('update %s set mailbox=?,serverMsg=NULL where id=?'
                                % tableName, (toBox, msg.uid))
        self.conn.commit()

    def blacklist(self, msgHeaders, blacklistTable='blacklist'):
        'add senders of these messages to our blacklist'
        bl = [get_headers_sender(t[1]) for t in msgHeaders]
        save_myaddrs_table(self.cursor, bl, blacklistTable)
        self.conn.commit()

    def _load_threads(self, tableName='messages'):
        'get thread mapping and set of my threads from db'
        self.cursor.execute('select id, threadID from %s where threadID is not null' % tableName)
        d = {}
        for uid, threadID in self.cursor.fetchall():
            d[uid] = threadID
        self.msgThread = d
        self.cursor.execute('select threadID from %s where fromMe=1 and threadID is not null'
                            % tableName)
        self.myThreads = set([t[0] for t in self.cursor.fetchall()])

    def get_answered_messages(self):
        return get_answered_messages(self.cursor)

def iter_mailboxes(mailDir):
    for fname in os.listdir(mailDir):
        path = os.path.join(mailDir, fname)
        if fname[0] == '.' and os.path.isdir(path):
            yield mailbox.Maildir(path, factory=None)


def canonical_name(a):
    name,addr = email.utils.parseaddr(a)
    if ',' in name:
        l = name.split(',')
        if len(l) == 2:
            name = ' '.join((l[1].strip(), l[0].strip()))
    return name, addr.lower()


def jost_pvalue(pvalues):
    'calculate Jost overall significance volume-integral'
    n = len(pvalues)
    logk = numpy.log(pvalues).sum()
    if logk >= 0.:
        return 1.
    i = numpy.arange(n)
    logR = (log(-logk) * i) - special.gammaln(i + 1)
    m = logR.max()
    return exp(logk + m + log(numpy.exp(logR - m).sum()))

def get_junkaddrs(c, p=0.05, maxreply=0, tableName='junkaddrs',
                  verdictTable='verdictaddrs'):
    c.execute('select email from notjunk')
    notjunk = frozenset([t[0] for t in c.fetchall()])
    c.execute('select email from %s where pval<? and nrelevant<=?'
              % tableName, (p, maxreply))
    junkaddrs = set([t[0] for t in c.fetchall() if t[0] not in notjunk])
    if verdictTable:
        c.execute('select email from %s where pval<? and nrelevant<=?' 
                  % verdictTable, (log(p / (1. - p)), maxreply))
        for t in c.fetchall():
            if t[0] not in notjunk:
                junkaddrs.add(t[0])
    return junkaddrs

def get_blacklist(c, blacklistTable='blacklist'):
    c.execute('select email from notjunk')
    notjunk = frozenset([t[0] for t in c.fetchall()])
    blackaddrs = set()
    c.execute('select email from %s' % blacklistTable)
    for t in c.fetchall():
        if t[0] not in notjunk:
            blackaddrs.add(t[0])
    return blackaddrs

def get_addrs(c, query='where pval<0.05', tableName='addrs'):
    'get set of addrs below specified p-value cutoff'
    c.execute('select email from %s %s' % (tableName, query))
    return frozenset([t[0] for t in c.fetchall()])

def get_headers_sender(headers):
    try:
        return email.utils.parseaddr(headers['from'])[1].lower()
    except KeyError:
        None

# conversions
# from, to
# date
# message-id
# flags

def db_connect(dbfile):
    'get connection that supports auto datetime conversion'
    return sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)

def create_messages_table(c, tableName='messages'):
    c.execute('''drop table if exists %s''' % tableName)
    c.execute('''create table %s
            (id integer primary key, 
            msgid text,
            serverID integer,
            serverMsg text,
            threadID integer,
            myThread integer,
            mailbox text,
            date integer,
            flags text,
            received text,
            sender text,
            fromMe integer,
            subject text,
            headers text,
            verdict integer)''' % tableName)
    c.execute('create unique index msgid on %s (msgid)' % tableName)
    c.execute('create index threadID on %s (threadID)' % tableName)

def create_threads_table(c):
    c.execute('''drop table if exists threads''')
    c.execute('''create table threads
            (id integer primary key, 
            threadID integer)''')

def save_threads(c, msgThread):
    for t in msgThread.items():
        c.execute('insert into threads values (?,?)', t)

def create_addrs_table(c, name='addrs'):
    c.execute('drop table if exists %s' % name)
    c.execute('''create table %s
            (email text primary key, 
            pval real,
            nrelevant integer,
            ntotal integer)''' % name)

def save_addrs(c, scores, tableName='addrs'):
    for p,m,n,a in scores:
        c.execute('insert into %s values (?,?,?,?)' % tableName, (a,p,m,n))

def save_myaddrs_table(c, myAddrs=(), tableName='myaddrs'):
    c.execute('''create table if not exists %s
            (email text primary key)''' % tableName)
    for a in myAddrs:
        c.execute('insert or ignore into %s values (?)' % tableName, (a,))

def get_all_recipients(m):
    tos = m.get_all('to', [])
    ccs = m.get_all('cc', [])
    resent_tos = m.get_all('resent-to', [])
    resent_ccs = m.get_all('resent-cc', [])
    return email.utils.getaddresses(tos + ccs + resent_tos + resent_ccs)

def is_from_me(m, myAddrs):
    'assess whether message is from me or not'
    origin = email.utils.getaddresses(m.get_all('from', []))
    origin = frozenset([t[1].lower() for t in origin])
    if not origin.isdisjoint(myAddrs):
        return True # sent by me
    else:
        received = m.get('received', None)
        recipients = get_all_recipients(m)
        recipients = frozenset([t[1].lower() for t in recipients])
        if received or not recipients.isdisjoint(myAddrs):
            return False # sent to me
        else:
            return None # can't tell if I sent this...

def save_sqlite3(mailboxes, myAddrs=None, dbfile='maildir.db', 
                 conn=None, newTable=True, tableName='messages', **kwargs):
    if not conn:
        conn = sqlite3.connect(dbfile)
    c = conn.cursor()
    if newTable:
        create_messages_table(c, tableName)
        conn.commit()
    if myAddrs: # save to database
        save_myaddrs_table(c, myAddrs)
        conn.commit()
    else: # read from database
        myAddrs = set()
        c.execute('select * from myaddrs')
        for t in c.fetchall():
            myAddrs.add(t[0].lower())
            
    for md in mailboxes:
        mboxName = os.path.basename(md._path)
        print 'saving %d messages: %s' % (len(md), mboxName)
        save_messages(c, md.iteritems(), myAddrs=myAddrs, mboxName=mboxName,
                      tableName=tableName, **kwargs)
        conn.commit()
    c.close()

def save_messages(c, messages, defaultTZ=7*3600, from_me_f=is_from_me, 
                  fromMe=None, myAddrs=None, mboxName=None, serverID=0,
                  verdict=None, tableName='messages'):
    for serverMsg,m in messages:
        if len(m) == 0: # no headers??
            continue
        if callable(from_me_f):
            fromMe = from_me_f(m, myAddrs)
        m.fromMe = fromMe # save flag on message object
        try:
            t = email.utils.parsedate_tz(m['date'])
            if not t:
                raise KeyError
            u = time.mktime(t[:9])
            if t[9]:
                date = datetime.datetime.fromtimestamp(u - t[9])
            else:
                date = datetime.datetime.fromtimestamp(u + defaultTZ)
        except (ValueError,KeyError):
            date = None
        try:
            flags = m.get_flags()
        except AttributeError:
            try:
                imapFlags = m._imapFlags
            except AttributeError:
                flags = None
            else:
                flags = 'IMAP:' + ','.join(imapFlags)
        d = {}
        for k,v in m.items():
            try:
                d[k.lower()] = unicode(v)
            except UnicodeDecodeError:
                d[k.lower()] = 'unknown encoding'
        headers = json.dumps(d)
        try:
            c.execute('insert or ignore into %s values (NULL,?,?,?,NULL,"NEW",?,?,?,?,?,?,?,?,?)'
                      % tableName,
                      (m['message-id'], serverID, serverMsg, 
                       mboxName, date, flags,
                       d.get('received', None), get_headers_sender(d),
                       fromMe, d.get('subject', None), headers, verdict))
            m.uid = c.lastrowid # save unique id
        except sqlite3.IntegrityError:
            pass

def save_verdicts(c, messages, mboxName, verdict, tableName='messages'):
    'record user triage decision of messages'
    for serverMsg,m in messages:
        try:
            msgID = m['message-id']
        except KeyError:
            continue
        c.execute('update %s set serverMsg=?, mailbox=?, verdict=? where msgid=?'
                  % tableName, (serverMsg, mboxName, verdict, msgID))
        #if c.rowcount != 1:
        #    warnings.warn('save_verdict: message-id %s not found or not unique, rowcount %d'
        #                  % (msgID, c.rowcount))


def get_my_message_ids(c):
    c.execute('select id from messages where fromMe=1')
    return frozenset([t[0] for t in c.fetchall()])

def get_subjects(c):
    d = {}
    c.execute('''select id,date as "[timestamp]",subject from messages 
                 where subject is not null and date is not null''')
    for uid, msgDate, subject in c.fetchall():
        l = subject.split()
        subject = ''
        for i,w in enumerate(l): # remove initial RE: from subject
            if w.lower() != 're:':
                subject = ' '.join(l[i:])
                break
        if subject:
            d.setdefault(subject, []).append((uid, msgDate))
    return d

def get_rank(l, v):
    left = 0
    right = len(l)
    while right - left > 1:
        mid = (left + right) / 2
        if l[mid] < v:
            left = mid
        else:
            right = mid
    return right

def subject_unreliability(subjectDict, threadTimes, subjectP=0.004, linkP=0.2):
    n = float(len(threadTimes))
    l = []
    d = {}
    for subject, messages in subjectDict.items():
        if len(messages) < 2:
            continue
        logP = 0.
        messages = [(t[1],t[0]) for t in messages]
        messages.sort()
        vals = []
        for i, msg1 in enumerate(messages[:-1]):
            timediff = messages[i + 1][0] - msg1[0]
            p = (n + 1 - get_rank(threadTimes, timediff)) / n
            vals.append((p, msg1[1], messages[i + 1][1]))
        p = jost_pvalue([t[0] for t in vals])
        l.append((p, subject))
        if p < subjectP and len(vals) > 1: # filter unreliable links
            vals = [t for t in vals if t[0] > linkP]
        if vals:
            d[subject] = vals
    l.sort()
    return l, d

def link_fusions(msgGraph, subjectFusions):
    for links in subjectFusions.values():
        for p, uid, uid2 in links:
            msgGraph.setdefault(uid, set()).add(uid2)
            msgGraph.setdefault(uid2, set()).add(uid)
            

def threadtime_roc(c, msgThread):
    c.execute('''select id,date as "[timestamp]" from messages
                 where date is not null''')
    d = {}
    for uid, msgDate in c.fetchall():
        try:
            threadID = msgThread[uid]
        except KeyError:
            continue
        d.setdefault(threadID, []).append(msgDate)
    roc = []
    for dates in d.values():
        dates.sort() # in ascending temporal order
        for date1 in dates[:-1]:
            roc.append(dates[-1] - date1)
    roc.sort()
    return roc

def subjects_roc(subjectDict, msgThread, maxDays=9999999):
    roc = []
    ntp = 0.
    subjectFP = {}
    for subject, messages in subjectDict.items():
        l = [(msgDate, msgThread[uid]) for (uid,msgDate) in messages
             if uid in msgThread] # assess vs. known threads
        if len(l) < 2: # no pairs to assess
            continue
        l.sort() # sort in ascending temporal order
        n = npair = 0
        for i,t in enumerate(l):
            msgDate1, thread1 = t
            for msgDate2, thread2 in l[i + 1:]:
                timediff = msgDate2 - msgDate1
                if timediff.days > maxDays:
                    continue
                if thread1 == thread2: # true positive
                    tp = 1
                else: # false positive
                    tp = 0
                roc.append((timediff, tp))
                n += tp
                npair += 1
        ntp += n
        subjectFP[subject] = (npair - n, npair) # save FP count
    roc.sort() # in order of timediff, smallest first
    nfp = len(roc) - ntp # total false positives
    tpsum = fpsum = 0
    l = []
    for timediff, tp in roc: # compute ROC curve
        tpsum += tp
        fpsum += 1 - tp
        l.append((timediff, tpsum / ntp, fpsum / nfp))
    return l, subjectFP, nfp / len(roc)

def extract_references(headers):            
    references = headers.get('references', '').split()
    try:
        r = headers['in-reply-to']
        if r not in references:
            references.append(r)
    except KeyError:
        pass
    return references

class MsgThreadDict(object):
    '''dict interface that takes message-id key and returns
    (id,threadID,myThread)'''
    def __init__(self, dbfile='maildir.db', tableName='threads'):
        self.conn = sqlite3.connect(dbfile)
        self.c = self.conn.cursor()
        self.tableName = tableName
    def __getitem__(self, msgID):
        self.c.execute('select id,threadID,myThread from %s where msgid=?' 
                       % self.tableName, (msgID,))
        v = self.c.fetchone()
        if v is None:
            raise KeyError('msgID not found')
        return v



def get_references(c, newOnly=True, tableName='messages'):
    'get {uid:[ref_msgid,]} refs and {msgid:uid} mapping'
    if newOnly:
        c.execute('select id,msgid,headers from %s where myThread="NEW"'
                  % tableName)
    else:
        c.execute('select id,msgid,headers from %s' % tableName)
    uidDict = {}
    msgDict = {}
    for uid,msgID,headers in c.fetchall():
        if not headers:
            continue
        headers = json.loads(headers)
        references = extract_references(headers)
        if references:
            uidDict[uid] = references
        if msgID:
            msgDict[msgID] = uid
    return uidDict, msgDict

def get_thread_graph(c, tableName='messages'):
    c.execute('select id,msgid,threadID from %s' % tableName)
    msgGraph = {}
    msgDict = {}
    for uid,msgID,threadID in c.fetchall():
        if threadID is not None and threadID != uid:
            uid2 = threadID
            msgGraph.setdefault(uid, set()).add(uid2)
            msgGraph.setdefault(uid2, set()).add(uid)
        if msgID:
            msgDict[msgID] = uid
    return msgGraph, msgDict

def get_dup_msgids(c, tableName='messages'):
    c.execute('select min(m1.id),m2.id from %s m1, %s m2 where m1.id<m2.id and m1.msgid is not null and m1.msgid=m2.msgid group by m2.id'
              % (tableName,tableName))
    return c.fetchall()

def delete_dups(c, dups, tableName='messages'):
    for uid,uid2 in dups:
        c.execute('delete from %s where id=?' % tableName, (uid2,))

def add_dup_edges(dups, msgGraph=None):
    if msgGraph is None:
        msgGraph = {}
    for uid,uid2 in dups:
        msgGraph.setdefault(uid, set()).add(uid2)
        msgGraph.setdefault(uid2, set()).add(uid)
    return msgGraph

def filter_thread_dups(threadMsgs, dupSet):
    r = {}
    for k,v in threadMsgs.items():
        v = filter(lambda uid: uid not in dupSet, v)
        if len(v) > 1:
            v.sort()
            r[v[0]] = v
    return r

def update_message_threads(c, threadMsgs, myThreads=None, tableName='messages',
                           erase=True):
    if erase: # erase existing data
        c.execute('update %s set threadID=NULL,myThread=NULL' % tableName)
    for threadID, msgs in threadMsgs.items():
        if myThreads is not None:
            myThread = threadID in myThreads
        else:
            myThread = None
        for uid in msgs:
            c.execute('update %s set threadID=?,myThread=? where id=?' 
                      % tableName, (msgs[0], myThread, uid))
    

def build_graph(uidDict, msgDict, msgGraph=None):
    if msgGraph is None:
        msgGraph = {}
    for uid, references in uidDict.items():
        for r in references:
            try:
                uid2 = msgDict[r]
                msgGraph.setdefault(uid, set()).add(uid2)
                msgGraph.setdefault(uid2, set()).add(uid)
            except KeyError:
                pass
    return msgGraph

def thread_dfs(uid, threadID, msgThread, threadMsgs, msgGraph):
    msgThread[uid] = threadID
    threadMsgs[threadID].append(uid)
    for uid2 in msgGraph[uid]:
        if uid2 not in msgThread:
            thread_dfs(uid2, threadID, msgThread, threadMsgs, msgGraph)

def get_threads(msgGraph):
    msgThread = {}
    threadMsgs = {}
    for uid in msgGraph:
        if uid not in msgThread:
            threadMsgs[uid] = []
            thread_dfs(uid, uid, msgThread, threadMsgs, msgGraph)
    return threadMsgs, msgThread

def get_my_threads(c, myMsgs, msgThread):
    myThreads = set()
    def add_msg(uid):
        try:
            myThreads.add(msgThread[uid])
        except KeyError:
            pass
    for i in myMsgs: # messages from me
        add_msg(i)
    c.execute('select id from messages where flags not null and flags not like "IMAP:%" and (flags like "%P%" or flags like "%R%")')
    for t in c.fetchall(): # maildir messages I answered or forwarded
        add_msg(t[0])
    c.execute('select id from messages where flags like "IMAP%\\Answered%" or flags like "IMAP%$Forwarded%"')
    for t in c.fetchall(): # IMAP messages I answered or forwarded
        add_msg(t[0])
    return myThreads

def reanalyze_threads(c):
    'add new messages to existing thread graph'
    print 'reanalyzing thread graph...'
    msgGraph, msgDict = get_thread_graph(c) # get old graph edges
    refsDict = get_references(c)[0] # get new graph edges
    msgGraph = build_graph(refsDict, msgDict, msgGraph)
    threadMsgs, msgThread = get_threads(msgGraph) # clique analysis
    myMsgs = get_my_message_ids(c)
    myThreads = get_my_threads(c, myMsgs, msgThread) # threads I participated in
    print 'updating threads db...'
    update_message_threads(c, threadMsgs, myThreads)
    print 'analyzing addr counts...'
    addrCounts = get_sender_counts(iter_senders(c), msgThread, myThreads)
    low, high = get_sender_pvals(addrCounts)
    print 'updating addrs db...'
    create_addrs_table(c)
    save_addrs(c, high)
    create_addrs_table(c, 'junkaddrs')
    save_addrs(c, low, 'junkaddrs')
    return threadMsgs, msgThread, myThreads, low, high

def iter_senders(c):
    c.execute('select id,headers from messages where fromMe=0 and msgid is not null and subject is not null')
    for uid, headers in c.fetchall():
        if not headers:
            continue
        headers = json.loads(headers)
        try:
            fromAddrs = headers['from']
        except KeyError:                    
            pass
        t = email.utils.parseaddr(fromAddrs)
        sender = t[1].lower()
        if sender:
            yield uid, sender

def get_sender_counts(senders, msgThread, myThreads, addrCounts=None):
    if addrCounts is None:
        addrCounts = {}
    for uid,sender in senders:
        if msgThread.get(uid, None) in myThreads:
            v = 1
        else:
            v = 0
        try:
            addrCounts[sender].append(v)
        except KeyError:
            addrCounts[sender] = [v]
    for k, v in addrCounts.items():
        addrCounts[k] = (sum(v), len(v))
    return addrCounts

def get_sender_pvals(addrCounts):
    M = sum([t[0] for t in addrCounts.values()])
    N = sum([t[1] for t in addrCounts.values()])
    low = []
    high = []
    for k,t in addrCounts.items():
        h = stats.hypergeom(N, M, t[1])
        low.append((h.cdf(t[0]), t[0], t[1], k))
        p = h.sf(t[0] - 1)
        if isnan(p): # old version of hypergeom.sf() gives NaN, yuck
            p = h.pmf(range(t[0], t[1] + 1)).sum()
        high.append((p, t[0], t[1], k))
    low.sort()
    high.sort()
    return low, high

def get_sender_verdicts(c, goodVerdicts, junkP=0.001, notjunkP=0.5, 
                        tableName='messages'):
    '''compute log likelihood odds ratio for two competing models notjunk/junk
    notjunk address: email will be kept (triaged) with likelihood notjunkP
    junk address: email will be kept (triaged) with likelihood junkP.
    returns [(LOD, m, n, address)] sorted with junk (lowest LOD) first'''
    keptLOD = log(notjunkP / junkP) # log likelihood odds ratio for kept email
    trashLOD = log((1. - notjunkP) / (1. - junkP)) # LLODR for trashed email
    addrs = []
    def save_data(a, k, t):
        addrs.append((k * keptLOD + t * trashLOD, k, t + k, a))
    c.execute('select sender, verdict from %s where verdict not null and myThread is not "NEW" order by sender' 
              % tableName)
    lastSender = None
    for sender, verdict in c.fetchall():
        if sender != lastSender:
            if lastSender:
                save_data(lastSender, kept, trashed)
            lastSender = sender
            kept = trashed = 0
        if verdict in goodVerdicts:
            kept += 1
        else:
            trashed += 1
    if lastSender:
        save_data(lastSender, kept, trashed)
    addrs.sort()
    return addrs


def get_word_counts(subjectDict, msgThread, myThreads, n=1):
    d = {}
    for subject, msgs in subjectDict.items():
        words = subject.split()
        phrases = set()
        for i in range(len(words) + 1 - n):
            phrases.add((' '.join(words[i:i + n])).lower())
        hits = []
        for t in msgs:
            if msgThread.get(t[0], None) in myThreads:
                hits.append(1)
            else:
                hits.append(0)
        for phrase in phrases:
            try:
                d[phrase] += hits
            except KeyError:
                d[phrase] = hits
    for k, v in d.items():
        d[k] = (sum(v), len(v))
    return d
    

def get_counts(mailDir):
    addrCounts = {}
    for md in iter_mailboxes(mailDir):
        for m in md:
            if 'S' not in m.get_flags(): # ignore unread messages
                continue
            name,addr = email.utils.parseaddr(m['from'])
            if 'R' in m.get_flags():
                r = 1
            else:
                r = 0
            try:
                addrCounts[addr].append(r)
            except KeyError:
                addrCounts[addr] = [r]
    for k, v in addrCounts.items():
        addrCounts[k] = (sum(v), len(v))
    return addrCounts

            
def get_answered_messages(c, tableName='messages'):
    'get unclosed messages with subsequent message fromMe in same thread'
    c.execute('select t1.id, t1.msgID from %s t1, %s t2 where t2.fromMe=1 and t1.threadID=t2.threadID and t1.date < t2.date and t1.mailbox!="Closed" and t1.mailbox!="Sent" and t1.serverID>0' 
              % (tableName, tableName))
    d = {}
    for uid, msgID in c.fetchall():
        d[msgID] = uid
    return d

        

    
