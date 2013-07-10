import db
import imap

def do_triage():
    import config
    servers = config.mailServers
    triageDB = db.TriageDB()
    for s in servers:
        print 'getting updates from %s...' % s.host
        s.get_updates(triageDB)
    triageDB.update_threads()
    for s in servers:
        print 'triaging messages on %s...' % s.host
        s.triage(triageDB)

if __name__ == '__main__':
    do_triage()
