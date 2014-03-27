#!/usr/bin/env python
# coding: utf-8
# This code is launched from a terminal window, e.g.
# python threaded_logging_server.py

__license__ = 'GPL v3'
__copyright__ = '2014, Gregory Riker'

import logging, os, re, socket, sqlite3, time, threading, SocketServer

class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):
    CREATE_NEW_TABLES = True
    SEND_RESPONSE = True

    INSERT_TEMPLATE = '''
        INSERT OR REPLACE INTO "{table_name}"
        ({columns})
        VALUES({values})'''

    TABLE_TEMPLATE = '''
        CREATE TABLE IF NOT EXISTS "{table_name}"
        ({columns})'''

    def __init__(self, parent, *args, **keys):
        self.db_path = parent.db_path
        self.log = logging.getLogger('plugin_logger')
        self.parent = parent
        SocketServer.BaseRequestHandler.__init__(self, *args, **keys)

    def add_new_table(self, plugin):
        '''
        Add a new table to the db
        '''
        args = {'table_name': plugin}
        ans = ''
        # Add the default calibre fields
        for key, value in self.parent.DEFAULT_FIELDS['CALIBRE'].items():
            ans += "{0} {1}, ".format(key, value)

        # Add the default plugin fields
        plugin_fields = {'plugin_version': 'TEXT'}
        for key, value in plugin_fields.items():
            ans += "{0} {1}, ".format(key, value)

        # Add timestamp and events fields
        ans += "timestamp DATETIME, logins INTEGER"
        args['columns'] = ans

        conn = sqlite3.connect(self.db_path)
        conn.execute(self.TABLE_TEMPLATE.format(**args))

    def handle(self):
        '''
        GET / HTTP/1.1\r\nAccept-Encoding: identity\r\n
        Calibre_Version: 1.29.0\r\n
        Host: 192.168.1.105:8000\r\n
        User-Agent: Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.2.13) Gecko/20101210 Gentoo Firefox/3.6.13\r\n
        Calibre_Install_Uuid: cbd37a2b-0872-4f91-8fdc-1cd75d8c1e30\r\n
        Connection: close\r\n
        Calibre_Os: osx\r\n\r\n
        '''
        cur_thread = threading.current_thread()
        self.data = self.request.recv(1024)
        self.initialize_event(self.client_address[0])
        self.parse_header()
        plugin = self.event.get('calibre_plugin')

        self.log.info("Handling request from {0} in thread {1}, {2} active threads".format(
            self.client_address[0], cur_thread.name, threading.active_count()))

        if plugin is not None:
            if self.table_exists(plugin):
                self.validate_plugin_fields()
                if self.store_event():
                    if self.SEND_RESPONSE:
                        #self.request.sendall("Thanks for posting in thread {0}!".format(cur_thread.name))
                        self.request.sendall("logged to '{0}'".format(plugin))
                else:
                    if self.SEND_RESPONSE:
                        self.request.sendall("Server is busy")
            else:
                if self.SEND_RESPONSE:
                    self.request.sendall("Unable to log unsupported plugin '{0}'".format(plugin))
        else:
            # Reachability being tested, send a response

            conn = sqlite3.connect(self.db_path)
            args = {'table_name': 'sniffers',
                    'columns': "originating_ip, timestamp",
                    'values': "?, ?"
                   }
            values_template = self.INSERT_TEMPLATE.format(**args)
            values = [self.event['originating_ip'], self.now(conn)]
            with conn:
                conn.execute(values_template, tuple(values))

            self.log.info("Responding to empty header from {0}".format(self.client_address[0]))
            self.request.sendall("Online")

    def initialize_event(self, originating_ip):
        '''
        Construct a default event dict with the originating ip
        '''
        self.event = dict.fromkeys(self.parent.DEFAULT_FIELDS['CALIBRE'], None)
        self.event['originating_ip'] = originating_ip

    def now(self, conn):
        c = conn.cursor()
        c.execute("SELECT datetime('now', 'localtime')")
        return c.fetchone()[0]

    def parse_header(self):
        '''
        Parse header lines for CALIBRE_ or PLUGIN_
        Populates a dict of {field: value} from matching lines
        '''
        pattern = re.compile(r"(?P<field>(CALIBRE_|PLUGIN_|DEVICE_).*?): (?P<value>.*?)$", re.IGNORECASE)
        lines = self.data.splitlines()
        for line in lines:
            matches = pattern.match(line)
            if matches:
                self.event[matches.groupdict()['field'].lower()] = matches.groupdict()['value']

        # Get appended query
        method, path, _ = lines[0].split()
        path = path.lstrip('/')
        self.query_string = None
        if '?' in path:
            self.query_string = path.split('?')[1]
            self.log.info("query from {0}: {1}".format(self.client_address[0], self.query_string))

    def store_event(self):
        """
        Store the (populated) event data to the db
        """
        stored = False
        if self.event.get('calibre_plugin') is not None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                # Previous logins?
                cur = conn.cursor()
                cur.execute('''SELECT logins FROM "{0}"
                               WHERE device_udid = "{1}"'''.format(
                               self.event['calibre_plugin'],
                               self.event['device_udid']))
                row = cur.fetchone()

                # Bump the login count
                if row:
                    logins = row[b'logins'] + 1
                else:
                    logins = 1

                # Construct the args for this entry
                event_keys = list(self.event.keys())
                event_keys.remove('calibre_plugin')
                event_keys.sort()
                args = {'table_name': self.event['calibre_plugin'],
                        'columns': ", ".join(event_keys) +
                                             ', timestamp, logins',
                        'values': ", ".join(['?' for e in event_keys]) + ', ?, ?'}

                values_template = self.INSERT_TEMPLATE.format(**args)

                # Construct a list of values to be inserted in the table
                values = []
                for key in event_keys:
                    values.append(self.event[key])
                # Add the timestamp
                values.append(self.now(conn))
                # Add the logins count
                values.append(logins)
                with conn:
                    conn.execute(values_template, tuple(values))
                stored = True
            except Exception as e:
                self.log.error("Error: {0} ({1} active threads)".format(e, threading.active_count()))
        return stored

    def table_exists(self, plugin):
        '''
        Confirm existence of table for specified plugin
        '''
        ans = False
        if plugin is not None:
            conn = sqlite3.connect(self.db_path)
            with conn:
                cur = conn.cursor()
                cur.execute('''PRAGMA table_info("{0}")'''.format(plugin))
                if len(cur.fetchall()) > 0:
                    ans = True
                else:
                    # Optionally create the specified table
                    if self.CREATE_NEW_TABLES:
                        self.add_new_table(plugin)
                        ans = True
        return ans

    def validate_plugin_fields(self):
        '''
        Make sure that the db knows about all the reported fields
        '''
        if self.event.get('calibre_plugin') is not None:
            plugin = self.event['calibre_plugin']

            # Get the existing columns
            conn = sqlite3.connect(self.db_path)
            with conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute('''SELECT * FROM "{0}"'''.format(plugin))
                existing_fields = [f[0] for f in cur.description]

            event_fields = [key for key in self.event.keys() if key.lower().startswith('plugin_')]

            for ef in event_fields:
                if ef not in existing_fields:
                    # Add new field to table
                    with conn:
                        cur = conn.cursor()
                        cur.execute('''ALTER TABLE "{0}" ADD COLUMN "{1}" TEXT'''.format(plugin, ef))


class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass


class PluginEventLogger(object):
    """
    Creates a sqlite db
    To create empty tables for specific plugins, add a 'PLUGINS' dict to DEFAULT_FIELDS
    with a list of plugin_* fields
    DEFAULT_FIELDS = {
        'CALIBRE': [
            'originating_ip',
            'calibre_install_uuid',
            'calibre_os',
            'calibre_version',
            ],
        'PLUGINS': {
            'Plugin One': {'plugin_version': 'TEXT'},
            'Plugin Two': {'plugin_version': 'TEXT'}
            }
        }

    """
    HOST = ''
    PORT = 7584
    LOGGING_FOLDER = os.path.join(os.path.expanduser('~'), 'Documents', 'Plugin logger')
    LOGGING_DB = "connections.db"

    # Default calibre-related fields to store in tables
    DEFAULT_FIELDS = {
        'CALIBRE': {
            'originating_ip': 'TEXT',
            'calibre_os': 'TEXT',
            'calibre_version': 'TEXT',
            'device_model': 'TEXT',
            'device_os': 'TEXT',
            'device_udid': 'TEXT UNIQUE',
            },
        }

    TABLE_TEMPLATE = '''
        CREATE TABLE IF NOT EXISTS "{table_name}"
        ({columns})'''

    def __init__(self):
        logging.basicConfig(filename=os.path.join(os.path.expanduser('~'), self.LOGGING_FOLDER, 'connections.log'),
            filemode='w',
            level=logging.DEBUG,
            format='%(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.log = logging.getLogger('plugin_logger')

    def instantiate_db(self):
        '''
        Create the db with the specified tables and default columns
        '''
        self.db_path = os.path.join(self.LOGGING_FOLDER, self.LOGGING_DB)
        db_existed = os.path.exists(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if not db_existed:
            conn.execute('''PRAGMA user_version={0}'''.format(1))

        # Create the sniffers table
        args = {'table_name': 'sniffers'}
        args['columns'] = "originating_ip TEXT UNIQUE, timestamp DATETIME"
        conn.execute(self.TABLE_TEMPLATE.format(**args))

        # Create the default plugin tables
        if self.DEFAULT_FIELDS.get('PLUGINS'):
            for plugin in self.DEFAULT_FIELDS['PLUGINS']:
                args = {'table_name': plugin}
                ans = ''
                # Add the default calibre fields
                for key, value in self.DEFAULT_FIELDS['CALIBRE'].items():
                    ans += "{0} {1}, ".format(key, value)

                # Add the default plugin fields
                for key, value in self.DEFAULT_FIELDS['PLUGINS'][plugin].items():
                    ans += "{0} {1}, ".format(key, value)

                # Add a timestamp field
                ans += "timestamp DATETIME"
                args['columns'] = ans
                conn.execute(self.TABLE_TEMPLATE.format(**args))

    def handler_factory(self):
        def createHandler(*args, **keys):
            return ThreadedTCPRequestHandler(self, *args, **keys)
        return createHandler

    def launch_server(self):
        server = ThreadedTCPServer((self.HOST, self.PORT), self.handler_factory())
        self.log.info("launching plugin logging server")
        server.serve_forever()

def main():
    pel = PluginEventLogger()
    pel.instantiate_db()
    pel.launch_server()

if __name__ == '__main__':
    main()

