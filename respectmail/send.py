import smtplib
from email.mime.text import MIMEText
from getpass import getpass


class SMTPServer(object):
    'wrapper for SSL SMTP connection'
    def __init__(self, host, user, password=None, port=465):
        if password is None:
            password = getpass('Enter password for %s on %s:' %
                               (user, host))
        self.host = host
        self.server = smtplib.SMTP_SSL(host, port)
        #self.server.set_debuglevel(1)
        self.server.login(user, password)

    def sendmail(self, from_addr, to_addrs, msg):
        self.server.sendmail(from_addr, to_addrs, msg.as_string())
        
    def quit(self):
        self.server.quit()


def get_draft_templates(srv, mbox='Drafts'):
    'return template dict and list of messages to template'
    templateDict = {}
    outList = []
    for msgID, msg in srv.get_messages(mbox):
        if msg.get('Subject', '').startswith(':template:'):
            templateName = msg['Subject'].split()[1]
            templateDict[templateName] = msg.get_payload()
        elif not msg.is_multipart() \
             and msg.get_payload().startswith(':respect:'): # apply template
            d = {}
            for line in msg.get_payload().split('\n'):
                s = line.split()
                if len(s) >= 2 and s[0].startswith(':') and s[0].endswith(':'):
                    token = s[0][1:-1] # strip off ::
                    d[token] = line[line.index(s[1]):].rstrip()
            outList.append((msgID, d, msg))
    return templateDict, outList

def apply_templates(srv, smtpServer, templateDict, msgList, expunge=True):
    'generate messages using templates, and send'
    msgSent = []
    for msgID, d, msg in msgList:
        name = d['respect'] # template name
        try:
            t = templateDict[name]
        except KeyError:
            print 'Warning: Ignoring unknown template:', name
            continue
        try:
            text = t % d # inject as python format string kwargs
        except KeyError, e:
            print 'Template message missing required kwarg:', d, e 
            continue # nothing to send, so skip
        msg.set_payload(text)
        msg.add_header('Bcc', msg['From']) # relay copy to myself
        recipients = msg.get_all('To', []) + msg.get_all('Cc', []) \
                     + msg.get_all('Bcc', [])
        smtpServer.sendmail(msg['From'], recipients, msg)
        msgSent.append(msgID) # schedule for deletion
    if msgSent: # delete the Drafts messages that were successfully sent
        print 'Sent %d template messages on %s' % (len(msgSent), srv.host)
        srv.server.delete_messages(msgSent)
        if expunge:
            srv.server.expunge()

def send_all_templates(servers, host, user, mbox='Drafts', expunge=True):
    'send all template messages on the specified servers'
    smtpServer = None
    for srv in servers:
        templateDict, msgList = get_draft_templates(srv, mbox)
        if msgList:
            if not smtpServer:
                smtpServer = SMTPServer(host, user) # get SMTP connection
            apply_templates(srv, smtpServer, templateDict, msgList, expunge)
    if smtpServer is not None:
        smtpServer.quit()


