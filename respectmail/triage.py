import db
import imap
import send

def get_servers():
    'get connections to server(s) specified by our config file'
    try:
        import config
    except ImportError:
        import sys
        import os
        sys.path.append(os.getcwd()) # look for config in current dir
        import config
    servers = config.mailServers
    return servers, getattr(config, 'smtpKwargs', {})

def do_triage(servers):
    'analyze incoming mail and perform candidate triage'
    triageDB = db.TriageDB()
    for s in servers:
        print 'getting updates from %s...' % s.host
        s.get_updates(triageDB)
    triageDB.update_threads((imap.REQUESTS, imap.FYI, imap.CLOSED))
    for s in servers:
        print 'triaging messages on %s...' % s.host
        s.triage(triageDB)
    return triageDB

def triage_ask_purge(servers, smtpKwargs):
    'triage, then give user a chance to reclassify, and finally purge spam'
    triageDB = do_triage(servers)
    for srv in servers:
        srv.server._disconnect() # avoid socket timeout in case user delays
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
            srv.server._connect() # refresh connection
            srv.purge_blacklist(triageDB)
            srv.server._disconnect() # go offline to avoid socket timeout

def repeat_triage_until_exit(servers, smtpKwargs):
    'let user triage incoming email over & over (enter password only once)'
    while True:
        triage_ask_purge(servers, smtpKwargs)
        confirm = raw_input('''Hit enter to re-connect and triage new messages, or enter X to exit: ''')
        if confirm.lower() == 'x':
            return
            
if __name__ == '__main__':
    servers, smtpKwargs = get_servers()
    repeat_triage_until_exit(servers, smtpKwargs)
