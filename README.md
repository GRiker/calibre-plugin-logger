Calibre plugin logger
=====================

A python client and server that logs metrics posted from calibre plugins.

Requirements:
* calibre command line tools

To experiment on a development machine, open a terminal window and execute
```python server.py```

Open another terminal window, execute
```calibre-debug client.py```

To terminate the server, send a SIGTERM signal to the server PID:

```ps -A | grep server.py```

```kill -TERM <PID>```

where ```<PID>``` is the PID of the ```python server.py``` process displayed by the first command.