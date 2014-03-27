#!/usr/bin/env python
# coding: utf-8
# This code needs to be run within the context of a plugin, or calibre-debug

import mechanize, time
from threading import Thread
from calibre import browser
from calibre.constants import (__appname__, __version__, iswindows, isosx,
        isportable, is64bit)
from calibre.utils.config import prefs        

class PhoneHome(Thread):
    '''
    Post an event to the logging server
    '''
    #URL = "http://192.168.1.105:7584"
    URL = "http://calibre-plugins.dnsd.info:7584"
    
    WAIT_FOR_RESPONSE = True
    def __init__(self, plugin=None, version="0"):
        Thread.__init__(self)
        self.plugin = plugin
        self.plugin_version = str(version)
        self.construct_header()

    def construct_header(self):
        '''
        Build the default header information describing the environment
        '''
        self.req = mechanize.Request(self.URL)
        self.req.add_header('CALIBRE_VERSION', __version__)
        self.req.add_header('CALIBRE_OS', 'win' if iswindows else 'osx' if isosx else 'oth')
        self.req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
        self.req.add_header('CALIBRE_PLUGIN', self.plugin)
        self.req.add_header('PLUGIN_VERSION', self.plugin_version)
        #print self.req.header_items()
        
        
    def run(self):
        br = browser()
        try:
            if self.WAIT_FOR_RESPONSE:
                ans = br.open(self.req).read().strip()            
                print ans
            else:
                br.open_novisit(self.req)
                
        except Exception as e:
            import traceback
            print traceback.format_exc()
                      
def main():
    #URL = "http://192.168.1.105:7584"
    URL = "http://casaalegria.homeip.net:7584"
    br = browser()
    try:
        br.open(URL)
        if False:
            for x in range(0):
                post = PhoneHome(plugin='Sample Plugin One', version=x)
                post.start()
                time.sleep(.01)
            for x in range(0):
                post = PhoneHome(plugin='Sample Plugin Two', version=x)
                post.start()
                time.sleep(.01)

        if False:
            # Post a request with new field variables
            post = PhoneHome(plugin='Sample Plugin One', version="1.2.3")
            post.req.add_header('PLUGIN_BOOK_COUNT', '50')
            post.req.add_header('PLUGIN_SOME_OTHER_VALUE', 'abcde')
            post.start()
        
        # Post a request to an new plugin
        PhoneHome(plugin='Marvin XD', version=1.23).start()

        # Post a request to an new plugin
        PhoneHome(plugin='iOS reader applications', version=1.23).start()
        
    except:
        print "Unable to reach server"
        import traceback
        print traceback.format_exc()

if __name__ == '__main__':   
    main()
