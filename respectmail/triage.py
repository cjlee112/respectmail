import db
import imap
import send

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
    return triageDB, servers, getattr(config, 'smtpKwargs', {})

if __name__ == '__main__':
    triageDB, servers, smtpKwargs = do_triage()
    d = dict(btname=servers[0].mboxlist[imap.BLACKLISTTRIAGE],
             blname=servers[0].mboxlist[imap.BLACKLIST]) # get mbox names
    print '''
Please review messages in %(btname)s, and move or delete
messages that you do NOT want to blacklist.  By default, messages left
in %(btname)s will be blacklisted.
''' % d
    confirm = raw_input('''When ready, enter Y to purge %(blname)s and %(btname)s,
    and SEND any :respect: template messages in Drafts
    (or any other key to postpone to later): ''' % d)
    if confirm.lower() == 'y':
        send.send_all_templates(servers, **smtpKwargs)
        for srv in servers:
            print 'purging blacklisted messages from %s...' % srv.host
            srv.purge_blacklist(triageDB)
