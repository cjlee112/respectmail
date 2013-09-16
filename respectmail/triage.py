import db
import imap

def do_triage():
    try:
        import config
    except ImportError:
        import sys
        import os
        sys.path.append(os.getcwd()) # look for config in current dir
        import config

    servers = config.mailServers
    triageDB = db.TriageDB()
    for s in servers:
        print 'getting updates from %s...' % s.host
        s.get_updates(triageDB)
    triageDB.update_threads((imap.REQUESTS, imap.FYI, imap.CLOSED))
    for s in servers:
        print 'triaging messages on %s...' % s.host
        s.triage(triageDB)

if __name__ == '__main__':
    do_triage()
