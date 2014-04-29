##Calibre plugin logger##

A lightweight python server that logs events posted from calibre plugins.

Requirements:

* calibre command line tools
* Python 2.7.5 (or newer, not 3.x) recommended for server

To experiment on a development machine:

* Create a folder on your development machine, e.g. <tt>server_test</tt>
* Copy <tt>server.py</tt> and <tt>client.py</tt> into that folder
* Open a terminal window in that folder
* Launch the server: ```python server.py```
* The databases will be created and monitoring begins

To send logging events to the server:

* Open another terminal window
* execute ```calibre-debug client.py``` to send sample events to the logging server

To gracefully exit the server, send a TERM signal to the server PID:

* ```ps -A | grep server.py```
* ```kill -TERM <PID>``` where ```<PID>``` is the PID of the ```python server.py``` process displayed by the first command.
* Or, __ctrl-c__ to inelegantly kill the process.

To deploy on your server:

* edit server.py (#14): ```DEVELOPMENT = False```
* Create the folder on your server where the logging databases will be stored
* Copy server.py to that folder
* edit server.py (#21) to point to your deployment folder
* cd to your logging folder
* ```python server.py```

If you want to deploy a logging server, I recommend [WebHostPython](https://www.webhostpython.com) with hosted VPS plans starting at $20/month. They have excellent customer support and can set up a server very quickly.

If you sign up using coupon code __GRSL__, we'll both benefit.
For more information, contact <sales@webhostpython.com>.
