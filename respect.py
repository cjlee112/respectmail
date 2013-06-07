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


# conversions
# from, to
# date
# message-id
# flags

def db_connect(dbfile):
    'get connection that supports auto datetime conversion'
    return sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)

def create_messages_table(c):
    c.execute('''drop table if exists messages''')
    c.execute('''create table messages
            (id integer primary key, 
            msgid text,
            mailbox text,
            date integer,
            flags text,
            received text,
            fromMe integer,
            subject text,
            headers text)''')

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

def save_addrs(c, scores, name='addrs'):
    for p,m,n,a in scores:
        c.execute('insert into %s values (?,?,?,?)' % name, (a,p,m,n))

def save_myaddrs_table(c, myAddrs):
    c.execute('''create table if not exists myaddrs
            (email text primary key)''')
    for a in myAddrs:
        c.execute('insert into myaddrs values (?)', (a,))

def get_all_recipients(m):
    tos = m.get_all('to', [])
    ccs = m.get_all('cc', [])
    resent_tos = m.get_all('resent-to', [])
    resent_ccs = m.get_all('resent-cc', [])
    return email.utils.getaddresses(tos + ccs + resent_tos + resent_ccs)

def save_sqlite3(mailboxes, myAddrs=None, dbfile='maildir.db', 
                 conn=None, defaultTZ=8*3600, newTable=True):
    if not conn:
        conn = sqlite3.connect(dbfile)
    c = conn.cursor()
    if newTable:
        create_messages_table(c)
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
        for m in md:
            if len(m) == 0: # no headers??
                continue
            received = m.get('received', None)
            if received: # sent to me
                fromMe = False
            else:
                origin = email.utils.getaddresses(m.get_all('from', []))
                origin = frozenset([t[1].lower() for t in origin])
                if not origin.isdisjoint(myAddrs):
                    fromMe = True # sent by me
                else:
                    recipients = get_all_recipients(m)
                    recipients = frozenset([t[1].lower() for t in recipients])
                    if not recipients.isdisjoint(myAddrs):
                        fromMe = False # sent to me
                    else:
                        fromMe = None # can't tell if I sent this...
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
            flags = m.get_flags()
            d = {}
            for k,v in m.items():
                try:
                    d[k.lower()] = unicode(v)
                except UnicodeDecodeError:
                    d[k.lower()] = 'unknown encoding'
            headers = json.dumps(d)
            try:
                c.execute('insert into messages values (NULL,?,?,?,?,?,?,?,?)',
                          (m['message-id'], mboxName, date, flags, received, 
                           fromMe, d.get('subject', None), headers))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
    c.close()

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
            

def get_references(c):
    c.execute('select id,msgid,headers from messages')
    uidDict = {}
    msgDict = {}
    for uid,msgID,headers in c.fetchall():
        if not headers:
            continue
        headers = json.loads(headers)
        references = headers.get('references', '').split()
        try:
            r = headers['in-reply-to']
            if r not in references:
                references.append(r)
        except KeyError:
            pass
        if references:
            uidDict[uid] = references
        if msgID:
            msgDict[msgID] = uid
    return uidDict, msgDict

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

def get_my_threads(myMsgs, msgThread):
    myThreads = set()
    for i in myMsgs:
        try:
            myThreads.add(msgThread[i])
        except KeyError:
            pass
    return myThreads

def get_sender_counts(c, msgThread, myThreads):
    c.execute('select id,headers from messages where fromMe=0 and msgid is not null and subject is not null')
    addrCounts = {}
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
        if not sender:
            continue
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

            
