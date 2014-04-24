#!/usr/bin/env python
# coding: utf-8
# This code is launched from a terminal window, e.g.
# python server.py

__license__ = 'GPL v3'
__copyright__ = '2014, Gregory Riker'

import argparse, hashlib, json, logging, os, re, signal, socket, sqlite3
import time, threading, urllib, SocketServer

# Version for newly minted DBs
CURRENT_DB_VERSION = 1
DEVELOPMENT = True

if DEVELOPMENT:
    # For testing, LOGGING_FOLDER is a folder on your development machine
    LOGGING_FOLDER = os.path.join(os.path.expanduser('~'), 'Desktop', 'Plugin logger')
else:
    # For deployment, LOGGING_FOLDER is a folder on your server
    LOGGING_FOLDER = os.path.join(os.path.sep, 'path_to', 'plugin_logging', 'folder')

COUNTRIES_DB = "Countries.db"
REGISTERED_PLUGINS_DB = "Registered plugins.db"
REGISTERED_PLUGINS_TABLE = "Registered plugins"

INSERT_TEMPLATE = '''
    INSERT OR REPLACE INTO "{table_name}"
    ({columns})
    VALUES({values})'''

TABLE_TEMPLATE = '''
    CREATE TABLE IF NOT EXISTS "{table_name}"
    ({columns})'''


class SchemaUpgrade(object):

    def __init__(self, conn, plugin, log):
        '''
        Upgrade an existing database through available schema upgrades
        Each upgrade_version_xx takes db from xx to xx+1
        '''

        self.log = log
        self.conn = conn
        self.cursor = conn.cursor()
        self.cursor.execute('BEGIN EXCLUSIVE TRANSACTION')

        updates = 0
        try:
            while True:
                uv = self.cursor.execute('pragma user_version').next()[0]
                meth = getattr(self, 'upgrade_version_%d' % uv, None)
                if meth is None:
                    break
                else:
                    self.log.info("Upgrading '%s' to version %d..." % (plugin, uv+1))
                    meth()
                    self.cursor.execute('pragma user_version=%d'%(uv+1))
                    updates += 1
        except:
            import traceback
            self.log.error(traceback.format_exc())
            self.cursor.execute('ROLLBACK')
            raise
        finally:
            conn.close()

        if not updates:
            self.log.info("plugin '{0}' up to date".format(plugin))

    def _upgrade_version_1(self):
        '''
        To enable this schema upgrade, remove leading underscore from method name
        '''
        self.log.info("updating DB from version 1 to version 2")


class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):

    def __init__(self, parent, *args, **keys):
        self.db_path = None
        self.countries_db_path = os.path.join(LOGGING_FOLDER, COUNTRIES_DB)
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
        conn.execute(TABLE_TEMPLATE.format(**args))

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
        self.parse_header()
        plugin = self.event.get('calibre_plugin')

        if False:
            self.log.info("Handling request from {0} in thread {1}, {2} active threads".format(
                self.event['country'], cur_thread.name, threading.active_count()))

        if plugin is not None:
            if self.plugin_db_registered(plugin):
                if self.store_event():
                    self.request.sendall("event logged to '{0}'".format(plugin))
                else:
                    self.request.sendall("server is busy")
            else:
                self.log.info("request to log unregistered plugin '{0}' from {1} ({2})".format(
                    plugin, self.event.get('originating_ip'), self.event.get('country')))
                self.request.sendall("unregistered plugin '{0}', event not logged".format(plugin))
        else:
            self.request.sendall(self.client_address[0])

    def parse_header(self):
        '''
        Parse header lines for CALIBRE_ or PLUGIN_
        Populates a dict of {field: value} from matching lines
        '''
        self.event = {}
        pattern = re.compile(r"(?P<field>(CALIBRE_|PLUGIN_).*?): (?P<value>.*?)$", re.IGNORECASE)
        _lines = self.data.splitlines()
        lines = [line for line in _lines if line.strip()]
        for line in lines:
            matches = pattern.match(line)
            if matches:
                self.event[matches.groupdict()['field'].lower()] = matches.groupdict()['value']

        # Get appended query
        self.query_string = None
        if lines:
            try:
                method, path, _ = lines[0].split()
                path = path.lstrip('/')
                if '?' in path:
                    self.query_string = path.split('?')[1]
            except:
                pass

    def store_event(self):
        """
        Store the (populated) event data to the db
        """
        stored = False
        if self.event.get('calibre_plugin') is not None:
            plugin = self.event.get('calibre_plugin')

            # Get the unique_logins_field for the plugin
            ap_conn = sqlite3.connect(os.path.join(LOGGING_FOLDER, REGISTERED_PLUGINS_DB))
            ap_conn.row_factory = sqlite3.Row
            ap_cur = ap_conn.cursor()
            ap_cur.execute('''SELECT default_fields, unique_logins_field
                              FROM "{0}"
                              WHERE plugin_name = "{1}"'''.format(
                              REGISTERED_PLUGINS_TABLE, plugin))
            row = ap_cur.fetchone()
            unique_logins_field = row[b'unique_logins_field']
            default_fields = json.loads(row[b'default_fields'])
            ap_conn.close()

            plugin_conn = sqlite3.connect(self.db_path)
            plugin_conn.row_factory = sqlite3.Row
            try:
                # Previous logins from unique_logins_field?
                cur = plugin_conn.cursor()
                if unique_logins_field is not None:
                    cur.execute('''SELECT logins FROM "{0}"
                                   WHERE "{1}" = "{2}"'''.format(
                                   plugin,
                                   unique_logins_field,
                                   self.event.get(unique_logins_field)))
                    row = cur.fetchone()
                else:
                    row = None

                # Bump the login count
                if row:
                    logins = row[b'logins'] + 1
                else:
                    logins = 1

                # Construct the args for this entry
                _event_keys = list(self.event.keys())
                _event_keys.remove('calibre_plugin')
                event_keys = [key for key in _event_keys if key in default_fields.keys()]
                unknown_keys = [key for key in _event_keys if key not in default_fields.keys()]

                event_keys.sort()
                columns = ", ".join(event_keys)
                values = ", ".join(['?' for e in event_keys])
                if unique_logins_field:
                    columns += ', logins'
                    values += ', ?'

                args = {'table_name': plugin,
                        'columns': columns,
                        'values': values}

                values_template = INSERT_TEMPLATE.format(**args)

                # Construct a list of values to be inserted in the table
                values = []
                for key in event_keys:
                    values.append(self.event[key])

                # Add the logins count if we're tracking logins
                if unique_logins_field:
                    values.append(logins)

                with plugin_conn:
                    cur.execute(values_template, tuple(values))
                stored = True

                for key in unknown_keys:
                    self.log.warning("WARNING: unrecognized key '{0}' ignored".format(key))

            except Exception as e:
                import traceback
                self.log.error(traceback.format_exc())
                self.log.error("Error: {0} ({1} active threads)".format(e, threading.active_count()))
        return stored

    def plugin_db_registered(self, plugin):
        '''
        Confirm existence of db supporting registered plugin
        If plugin DB is authorized, but doesn't exist, create it
        '''
        ans = False
        if plugin is not None:
            conn = sqlite3.connect(os.path.join(LOGGING_FOLDER, REGISTERED_PLUGINS_DB))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('''SELECT path, default_fields, field_order
                           FROM "{0}"
                           WHERE plugin_name = "{1}"'''.format(REGISTERED_PLUGINS_TABLE, plugin))
            authorized = cur.fetchone()
            conn.close()
            if authorized:
                self.db_path = os.path.join(LOGGING_FOLDER, authorized[b'path'])
                db_existed = os.path.exists(self.db_path)
                plugin_conn = sqlite3.connect(self.db_path)
                if not db_existed:
                    self.log.info("creating new DB for authorized plugin '{0}'".format(plugin))
                    with plugin_conn:
                        p_cur = plugin_conn.cursor()
                        p_cur.execute('''PRAGMA user_version={0}'''.format(CURRENT_DB_VERSION))
                        fields = json.loads(authorized[b'default_fields'])
                        field_order = json.loads(authorized[b'field_order'])
                        columns = ''
                        for field in field_order[:-1]:
                            columns += "{0} {1}, ".format(field, fields[field])
                        columns += "{0} {1}".format(field_order[-1], fields[field_order[-1]])
                        args = {'table_name': plugin,
                                'columns': columns}
                        p_cur.execute(TABLE_TEMPLATE.format(**args))
                ans = True
        return ans


class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass


class PluginEventLogger(object):
    """
    """
    if DEVELOPMENT:
        HOST = 'localhost'
        PORT = 8378             # TEST
    else:
        HOST = ''
        PORT = 7584             # PLUG

    def __init__(self):
        self.args = self.init_parser()
        self.log = self.initialize_logger()

    def initialize_dbs(self):
        '''
        Bootstrap the DBs for each authorized plugin
        '''
        # Create the Registered plugins DB
        plugins_db = os.path.join(LOGGING_FOLDER, REGISTERED_PLUGINS_DB)
        db_existed = os.path.exists(plugins_db)
        plugins_conn = sqlite3.connect(plugins_db)
        plugins_conn.row_factory = sqlite3.Row
        cur = plugins_conn.cursor()
        if not db_existed:
            self.log.info("creating '{0}'…".format(REGISTERED_PLUGINS_DB))
            plugins_conn.execute('''PRAGMA user_version = "{0}"'''.format(1))
            args = {'table_name': REGISTERED_PLUGINS_TABLE,
                    'columns': ("plugin_name TEXT UNIQUE, "
                                "path TEXT, "
                                "default_fields TEXT,"
                                "field_order TEXT, "
                                "unique_logins_field TEXT")}
            cur.execute(TABLE_TEMPLATE.format(**args))

            # Sample plugin 1: stores latest login only
            cur.execute('''INSERT INTO "{0}"
                            (plugin_name, path, default_fields, field_order, unique_logins_field)
                            VALUES(?, ?, ?, ?, ?)'''.format(REGISTERED_PLUGINS_TABLE),
                            ("Log latest",
                             "log_latest_connections.db",
                             json.dumps({'timestamp': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                                         'plugin_version': 'TEXT',
                                         'calibre_version': 'TEXT',
                                         'calibre_os': 'TEXT',
                                         'calibre_install_uuid': 'TEXT UNIQUE',
                                         'logins': 'INTEGER'}),
                             json.dumps(['timestamp', 'plugin_version', 'calibre_version',
                                         'calibre_os', 'calibre_install_uuid', 'logins']),
                             "calibre_install_uuid"
                            )
                       )

            # Sample plugin 2: stores all logins
            cur.execute('''INSERT INTO "{0}"
                            (plugin_name, path, default_fields, field_order, unique_logins_field)
                            VALUES(?, ?, ?, ?, ?)'''.format(REGISTERED_PLUGINS_TABLE),
                            ("Log all",
                             "log_all_connections.db",
                             json.dumps({'timestamp': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                                         'plugin_version': 'TEXT',
                                         'calibre_version': 'TEXT',
                                         'calibre_os': 'TEXT',
                                         'calibre_install_uuid': 'TEXT'}),
                             json.dumps(['timestamp', 'plugin_version', 'calibre_version',
                                         'calibre_os', 'calibre_install_uuid']),
                             None
                            )
                       )

            plugins_conn.commit()

        self.instantiate_plugin_dbs(cur)
        plugins_conn.close()

    def initialize_logger(self):
        log_file = os.path.join(os.path.expanduser('~'), LOGGING_FOLDER, 'plugin_logger.log')
        logging.basicConfig(
            filename=log_file,
            filemode='w',
            level=logging.DEBUG,
            format='%(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        log = logging.getLogger('plugin_logger')

        if not self.args.quiet:
            console = logging.StreamHandler()
            console.setLevel(logging.DEBUG)
            log.addHandler(console)
        return log

    def init_parser(self):
        '''
        '''
        parser = argparse.ArgumentParser(description="Server handling threader plugin logging events")
        parser.add_argument('-q', '--quiet', default=False, action='store_true', help='Suppress logging messages to console')
        return parser.parse_args()

    def handler_factory(self):
        def createHandler(*args, **keys):
            return ThreadedTCPRequestHandler(self, *args, **keys)
        return createHandler

    def instantiate_plugin_dbs(self, cur):
        '''
        Instantiate individual authorized plugin DBs as needed
        '''
        cur.execute('''SELECT plugin_name, path, default_fields, field_order, unique_logins_field
                       FROM "{0}"'''.format(REGISTERED_PLUGINS_TABLE))
        authorized_plugins = cur.fetchall()
        for row in authorized_plugins:
            db_path = os.path.join(LOGGING_FOLDER, row[b'path'])
            db_existed = os.path.exists(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            if not db_existed:
                plugin = row[b'plugin_name']
                self.log.info("creating '{0}' DB".format(plugin))
                conn.execute('''PRAGMA user_version={0}'''.format(CURRENT_DB_VERSION))
                fields = json.loads(row[b'default_fields'])
                field_order = json.loads(row[b'field_order'])
                columns = ''
                for field in field_order[:-1]:
                    columns += "{0} {1}, ".format(field, fields[field])
                columns += "{0} {1}".format(field_order[-1], fields[field_order[-1]])
                args = {'table_name': plugin,
                        'columns': columns}
                conn.execute(TABLE_TEMPLATE.format(**args))

            # Do the updates
            SchemaUpgrade(conn, row[b'plugin_name'], self.log)

    def launch_server(self):
        self.doneEvent = threading.Event()
        signal.signal(signal.SIGTERM, self.terminate)

        self.server = ThreadedTCPServer((self.HOST, self.PORT), self.handler_factory())
        if DEVELOPMENT:
            self.log.info("launching plugin logging server listening on {0}:{1}".format(self.HOST, self.PORT))
        else:
            self.log.info("launching plugin logging server listening on port {1}".format(self.PORT))
        self.server.serve_forever()

        self.doneEvent.wait()

    def shutdownHandler(self, msg, event):
        self.server.shutdown()
        self.log.info("shutdown complete")
        event.set()

    def terminate(self, signal, frame):
        self.log.info("SIGTERM received, shutting down…")
        t = threading.Thread(target = self.shutdownHandler, args = ('SIGTERM received', self.doneEvent))
        t.start()


def main():
    pel = PluginEventLogger()
    pel.initialize_dbs()
    pel.launch_server()

if __name__ == '__main__':
    main()

