
Respect Mail
------------

In a world of junk mail, you deserve a little respect...

RespectMail is an automatic email triage tool that works with
any IMAP server(s) you use.  It splits incoming email on the IMAP server
into several triage folders:

* Requests: messages that you are likely to answer
* FYI: messages that you may need to answer
* Closed: messages you've already answered
* Junk: messages from addresses that you always ignore
* messages where no clear determination is possible are left in
  your INBOX, for you to deal with.

It bases this on statistical analysis of your email history
(it reconstructs the thread structure of all your email conversations),
currently from the following possible sources:

* Maildir database of old messages;
* Apple Mail database of old messages (by way of converting it to Maildir);
* IMAP server(s);
* your curation of its triage predictions.  You do this simply by moving
  messages from a triage folder (e.g. RequestsTriage) to a "final verdict"
  folder (e.g. Requests), (or simply deleting messages that are not
  of interest to you), using whatever mail client you want.

RespectMail's predictions will get better and better as
it accumulates more and more historical data on what you consider
relevant vs. not.

**WARNING**: this is early stage alpha software, in active development,
likely to crash,
undocumented, not recommended for use by others -- for the moment.
As I keep using and improving this, I'll try to whip
this into a form usable for others.

install dependencies
--------------------

Currently

* Python
* imapclient
* it uses scipy for some statistical analysis; I will try to 
  modulate that requirement in future versions.

initial setup
-------------

* create the initial sqlite3 database in your current directory as follows::

    from respectmail import db
    tdb = db.TriageDB(createTables=True, myAddrs=('me@example.com', 'me@gmail.com'))

* write a ``config.py`` file that specifies what IMAP servers you
  want to triage::

    from respectmail import IMAPServer
    mailServers = [
      imap.IMAPServer('imap.example.com', 'me')
      imap.IMAPServer('imap.gmail.com', 'me@gmail.com', serverID=2),
      ]

How you use it
--------------

Assuming the sqlite3 database file (by default ``maildir.db``)
is in your current directory, you run a triage on all your IMAP
servers via::

  python /path/to/respectmail/triage.py

It will ask you for IMAP server password(s), get INBOX and Sent
mail headers, analyze data and perform the triage.

You should then use your regular email client to look at the
folders RequestsTriage, FYITriage and ClosedTriage.  Move messages
that were correct predictions to the corresponding folder
(i.e. Requests, FYI or Closed), or to whatever is the correct
location.  You can simply delete (or Junk, or archive, or whatever)
any messages that are not of interest to you.
Do the same thing for the "indeterminate" messages remaining in
your INBOX.

Rerun the respectmail triage whenever you need to.


Why Did I Start This?
---------------------

PROBLEM: my various email programs (Apple Mail, Gmail) were so full of
junk mail that it was getting hard to find the messages I actually care
about.  I ended up having to switch from a blacklisting strategy
(list the address you don't want to see) to a pure whitelisting
strategy (only show emails from the list of addresses explicitly
cleared as valid).  The blacklist would grow infinitely;
only the whitelist is finite...
The fundatmental problem is that essentially every organization we deal with
(in my case ranging
from my employer, UCLA, to every journal, group or company I've ever
had contact with) is vigorously deluging us with junk mail.  But
**Spam** filters are only looking for Viagra ads, phishing attempts
and obvious cons.  Unfortunately that's only the tip of the
junk mail iceberg.

It struck me that these spam filters are ignoring a simple, crucial
piece of information: what's the probability that I'm going to 
*respond* to a message from a given address?  This is an operational
criterion: people that I answer, may need answers in the future.
Emails that I steadfastly ignore (dozens of times) are a pretty safe
bet for ignoring in the future.

It also annoyed me that mail programs are typically take-it-or-leave-it:
a monolithic package of functionality that locks your content
inside itself (in the case of Apple Mail, using a format that is
not even officially documented).  This makes it hard to "get the best
of all worlds" by mixing different best-in-class tools; instead you're
typically stuck with one tool that tries to be a "one stop shop" for
managing all aspects of your email.  This seemed silly to me:
the IMAP standard provides a clean interface where we can mix
whatever tools we want.

I wanted to manage my mail using the power of data mining backends
and statistical algorithms.

I disliked the security risks associated with downloading every
received message to my computer.  Instead I want only headers
to enter my machine.
