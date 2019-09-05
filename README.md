PyUPnP
======
*Simple Python UPnP device library built in Twisted*

**NOTE:** PyUPnP doesn't implement ContentDirectory, ConnectionManager, etc.. services.

**We do** provide some shell classes with the actions, state variables and method signatures
already setup as per the UPnP spec, So all you need to do is inherit the shell class and
implement the methods.

See https://github.com/fuzeman/PyUPnP/blob/master/examples/mediaserver/main.py
for an example of how to get started.

### License ###

     PyUPnP - Simple Python UPnP device library built in Twisted
     Copyright (C) 2013 Dean Gardiner <gardiner91@gmail.com>
     
     This program is free software: you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation, either version 3 of the License, or
     (at your option) any later version.
     
     This program is distributed in the hope that it will be useful,
     but WITHOUT ANY WARRANTY; without even the implied warranty of
     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
     GNU General Public License for more details.
     
     You should have received a copy of the GNU General Public License
     along with this program. If not, see <http://www.gnu.org/licenses/>.

### Debugging / Logging ###

To enable debugging just call the following

     Logr.configure(logging.DEBUG)

----

     def configure(level=logging.WARNING, handler=None, formatter=None)

If **handler** is None it defaults to `logging.StreamHandler`

If **formatter** is None it defaults to an internal formatter found in the `logr` module


### Installation
PyUPnP can be installed globally by running

    sudo python setup.py install

or locally by running

    python setup.py install --user


### Usage
See the example mediaserver for basic usage.

To return variables in response to an action call, the action functions should return the variables 
in a dictionary:
```
return {'parameter1':value1, 'parameter2':value2}
```

If an upnp error needs to be returned, the action function can raise an `upnpError`:
```
from pyupnp.upnp import upnpError
...
raise upnpError(501, 'ActionFailed')
```
in which the first parameter is the `errorCode` and the second parameter is `errorDescription`.

