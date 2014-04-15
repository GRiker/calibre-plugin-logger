#!/usr/bin/env python
# coding: utf-8

__license__ = 'GPL v3'
__copyright__ = '2014, Gregory Riker'

"""
    This sample code needs to be run within the context of calibre-debug
    in order to access calibre environment variables
    calibre-debug client.py

    The client code attempts to post logging events to the server.
    If the server is not running, or not listening on the same port,
    the event will not be logged.

"""

import logging, mechanize, time
from threading import Thread
from calibre import browser
from calibre.constants import (__appname__, __version__, iswindows, isosx,
        isportable, is64bit)
from calibre.utils.config import prefs

SERVER_URL = "http://localhost:8378"


class PluginEventLogger(Thread):
    '''
    Post an event to the logging server
    '''
    URL = SERVER_URL

    def __init__(self, plugin=None, version="0", verbose=True):
        Thread.__init__(self)
        self.verbose = verbose
        self.plugin = plugin
        self.plugin_version = str(version)
        self.construct_header()

    def construct_header(self):
        '''
        Build the default header information describing the environment
        '''
        self.req = mechanize.Request(self.URL)
        self.req.add_header('CALIBRE_VERSION', __version__)
        self.req.add_header('CALIBRE_OS', 'Windows' if iswindows else 'OS X' if isosx else 'Linux')
        self.req.add_header('CALIBRE_PLUGIN', self.plugin)
        self.req.add_header('PLUGIN_VERSION', self.plugin_version)

    def run(self):
        br = browser()
        try:
            ans = br.open(self.req).read().strip()
            if self.verbose:
                logging.info("SERVER: {0}".format(ans))
        except Exception as e:
            import traceback
            print("ERROR: {0}".format(traceback.format_exc()))

def main():
    '''
    The server creates two sample authorized plugins, 'Log latest' and 'Log all'
    '''
    # Set up a logger with timestamp
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s.%(msecs)d: %(message)s', datefmt='%H:%M:%S')
    log = logging.getLogger('client')

    br = browser()
    try:
        br.open(SERVER_URL)
        if False:
            # Stress test: hit the server with 100 events per plugin in rapid succession
            iterations = 100
            log.info("CLIENT: starting stress test with {0} iterations…".format(iterations))
            DELAY = 0.01
            for x in range(iterations):
                post = PluginEventLogger(plugin='Log latest', version=x, verbose=False)
                post.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
                post.start()
                time.sleep(DELAY)

                post = PluginEventLogger(plugin='Log all', version=x, verbose=False)
                post.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
                post.start()
                time.sleep(DELAY)
            log.info("CLIENT: stress test complete")

        # Post regular events
        if True:
            # Post a request to 'Log latest' which uses unique installation_id
            log.info("CLIENT: logging to 'Log latest'…")
            post = PluginEventLogger(plugin="Log latest", version="1.2.3")
            post.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
            post.start()

            # Post a request to 'Log all' which uses unique installation_id
            log.info("CLIENT: logging to 'Log all'…")
            post = PluginEventLogger(plugin="Log all", version="2.3.4")
            post.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
            post.start()

        # Post a request for an unknown plugin
        if False:
            log.info("CLIENT: logging to 'Some other plugin'…")
            post = PluginEventLogger(plugin="Some other plugin", version="0.0.1")
            post.start()

        # Post a request to a registered plugin with new fields
        if True:
            post = PluginEventLogger(plugin='Log all', version="1.2.3")
            post.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
            post.req.add_header('PLUGIN_BOOK_COUNT', '50')
            post.req.add_header('PLUGIN_SOME_OTHER_VALUE', 'abcde')
            post.start()


    except:
        log.info("ERROR: Unable to reach server '{0}'".format(SERVER_URL))
        import traceback
        log.error(traceback.format_exc())

if __name__ == '__main__':
    main()
