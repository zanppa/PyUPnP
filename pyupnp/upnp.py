# PyUPnP - Simple Python UPnP device library built in Twisted
# Copyright (C) 2013  Dean Gardiner <gardiner91@gmail.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from lxml import etree
import time
from twisted.internet import reactor
from twisted.web.error import UnsupportedMethod
from twisted.web.resource import Resource
from twisted.web.server import Site
from pyupnp.logr import Logr
from pyupnp.util import twisted_absolute_path

__author__ = 'Dean Gardiner'

def parse_SOAP_RPC(xml_bytes):
    """Parse a UPnP SOAP request body and extract the arguments."""
    root = etree.fromstring(xml_bytes)

    # UPnP requests always embed the method name directly inside <s:Body>
    # Grab the first child of the Body element regardless of its namespace
    body_element = root.xpath('///*[local-name()="Body"]/*[1]')
    if not body_element:
        raise ValueError("Invalid SOAP structural format")

    action_element = body_element[0]
    # Remove namespace brackets if present to get clean action name
    action_name = action_element.tag.split('}')[-1]

    # Extract arguments mapping key -> text content
    arguments = {}
    for child in action_element:
        arg_name = child.tag.split('}')[-1]
        arguments[arg_name] = child.text

    return action_name, arguments



def build_SOAP(method='Response', namespace=None, kw=None):
    """ Build a compliant UPnP SOAP 1.1 response body.
    e.g., namespace = "urn:schemas-upnp-org:service:WANIPConnection:1"
          method = "GetExternalIPAddressResponse"
          kw = {"NewExternalIPAddress": "203.0.113.195"}
    """
    # Define UPnP standard SOAP namespaces
    NS_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
    NS_ENC = "http://schemas.xmlsoap.org/soap/encoding/"
    xsd = "http://www.w3.org/1999/XMLSchema"
    xsi = "http://www.w3.org/1999/XMLSchema-instance"
    nsmap = {
        'SOAP-ENV': NS_SOAP,
        'SOAP-ENC': NS_ENC,
        'xsd': xsd,
        'xsi': xsi
    }

    # Create the Envelope
    envelope = etree.Element(f"{{{NS_SOAP}}}Envelope", nsmap=nsmap)
    envelope.set(f"{{{NS_SOAP}}}encodingStyle", NS_ENC)

    # Create the Body
    body = etree.SubElement(envelope, f"{{{NS_SOAP}}}Body")

    # Create the Action Response Tag (UPnP dictates it must append 'Response')
    action_nsmap = {'ns1': namespace}
    action_response = etree.SubElement(
        body,
        f"{{{namespace}}}{method}",
        nsmap=action_nsmap
    )

    # Inject Output Arguments
    if kw:
        for key, value in kw.items():
            arg_elem = etree.SubElement(action_response, key)

            # Recursively append dictionary entries (e.g., UPnPError -> errorCode)
            def dict_to_xml(parent, dictionary):
                for k, v in dictionary.items():
                    child = etree.SubElement(parent, k)
                    if isinstance(v, dict):
                        dict_to_xml(child, v)
                    else:
                        child.text = str(v)

            if isinstance(value, dict):
                dict_to_xml(arg_elem, value)
            else:
                arg_elem.text = str(value)

    # Return raw XML bytes
    return etree.tostring(envelope, xml_declaration=True, encoding="utf-8")


class upnpError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.errorCode = code


def getHeader(request, name, required=True, default=None):
    result = request.requestHeaders.getRawHeaders(name)
    if len(result) != 1:
        if required:
            raise KeyError()
        else:
            return default
    return result[0]


class UPnP(Resource):
    def __init__(self, device):
        """UPnP Control Server

        :type device: Device
        """
        Resource.__init__(self)

        self.device = device
        self.running = False

    def listen(self, interface=''):
        if self.running:
            raise Exception()

        Logr.debug("listen()")
        self.site = Site(self)
        self.site_port = reactor.listenTCP(0, self.site, interface=interface)
        self.listen_address = self.site_port.socket.getsockname()[0]
        self.listen_port = self.site_port.socket.getsockname()[1]
        self.running = True

        self.device.location = "http://%s:" + str(self.listen_port)

        Logr.debug("listening on %s:%s", self.listen_address, self.listen_port)

    def stop(self):
        if not self.running:
            return

        Logr.debug("stop()")
        self.site_port.stopListening()
        self.running = False

    def getChild(self, path, request):
        # Hack to fix twisted not accepting absolute URIs
        path, request = twisted_absolute_path(path, request)

        if path == '':
            return ServeResource(self.device.dumps(), 'application/xml')

        for service in self.device.services:
            if path == service.serviceId:
                return ServiceResource(service)

        Logr.debug("unhandled request %s", path)
        return Resource()


class ServiceResource(Resource):
    def __init__(self, service):
        Resource.__init__(self)
        self.service = service

    def render(self, request):
        request.setHeader('Content-Type', 'application/xml')
        return self.service.dumps()

    def getChild(self, path, request):
        if path == 'event':
            return ServiceEventResource(self.service)

        if path == 'control':
            return ServiceControlResource(self.service)

        Logr.debug("(%s) unhandled request %s", self.service.serviceType, path)
        return Resource()


class ServiceControlResource(Resource):
    def __init__(self, service):
        Resource.__init__(self)
        self.service = service

    def render(self, request):
        try:
            return Resource.render(self, request)
        except UnsupportedMethod as e:
            Logr.debug("(%s) unhandled method %s",
                       self.service.serviceType, request.method)
            raise e

    def render_POST(self, request):
        data = request.content.getvalue()
        name, kwargs = parse_SOAP_RPC(data)

        Logr.debug("(%s) %s", self.service.serviceType, name)

        if name not in self.service.actions or name not in self.service.actionFunctions:
            raise NotImplementedError()

        action = self.service.actions[name]
        func = self.service.actionFunctions[name]

        for argument in action:
            if argument.direction == 'in':
                if argument.name in kwargs:
                    value = kwargs[argument.name]
                    del kwargs[argument.name]
                    kwargs[argument.parameterName] = value
                else:
                    raise TypeError()

        try:
            result = func(**kwargs)
        except upnpError as e:
            request.setResponseCode(500)
            fault = {'faultcode' : 's:Client', 'faultstring' : 'UPnPError'}
            fault['detail'] = {'UPnPError' : {'errorCode' : e.errorCode, 'errorDescription' : str(e)}}
            return build_SOAP(method='Fault', kw=fault, namespace='http://schemas.xmlsoap.org/soap/envelope/')

        #return buildSOAP(kw={
        #    '%sResponse' % name: result
        #})
        return build_SOAP(method='%sResponse' % name, kw=result, namespace=self.service.serviceType)


class ServiceEventResource(Resource):
    def __init__(self, service):
        Resource.__init__(self)
        self.service = service

    def _parse_nt(self, value):
        if value != 'upnp:event':
            raise ValueError()
        return value

    def _parse_callback(self, value):
        # TODO: Support multiple callbacks as per UPnP 1.1
        if '<' not in value or '>' not in value:
            raise ValueError()
        return value[value.index('<') + 1:value.index('>')]

    def _parse_timeout(self, value):
        if not value.startswith('Second-'):
            raise ValueError()
        return int(value[7:])

    def render(self, request):
        try:
            return Resource.render(self, request)
        except UnsupportedMethod as e:
            Logr.debug("(%s) %s", self.service.serviceType, request.method)
            raise e

    def render_SUBSCRIBE(self, request):
        Logr.debug("(%s) SUBSCRIBE", self.service.serviceType)

        if request.requestHeaders.hasHeader('sid'):
            # Renew
            sid = getHeader(request, 'sid')
            if sid in self.service.subscriptions:
                self.service.subscriptions[sid].last_subscribe = time.time()
                self.service.subscriptions[sid].expired = False
                Logr.debug("(%s) Successfully renewed subscription",
                           self.service.serviceType)
            else:
                Logr.debug("(%s) Received invalid subscription renewal",
                           self.service.serviceType)
        else:
            # New Subscription
            nt = self._parse_nt(getHeader(request, 'nt'))
            callback = self._parse_callback(getHeader(request, 'callback'))
            timeout = self._parse_timeout(getHeader(request, 'timeout', False))

            Logr.debug("(%s) %s %s", self.service.serviceType, callback, timeout)

            responseHeaders = self.service.subscribe(callback, timeout)
            if responseHeaders is not None and type(responseHeaders) is dict:
                for name, value in responseHeaders.items():
                    request.setHeader(name, value)
                return ''
            else:
                Logr.debug("(%s) SUBSCRIBE FAILED", self.service.serviceType)

    def render_UNSUBSCRIBE(self, request):
        Logr.debug("(%s) UNSUBSCRIBE", self.service.serviceType)

        if request.requestHeaders.hasHeader('sid'):
            # Cancel
            sid = getHeader(request, 'sid')
            if sid in self.service.subscriptions:
                self.service.subscriptions[sid].expired = True
                Logr.debug("(%s) Successfully unsubscribed", self.service.serviceType)
            else:
                Logr.debug("(%s) Received invalid UNSUBSCRIBE request", self.service.serviceType)
        else:
            Logr.debug("(%s) Received invalid UNSUBSCRIBE request", self.service.serviceType)


class ServeResource(Resource):
    def __init__(self, data, mimetype):
        Resource.__init__(self)
        self.data = data
        self.mimetype = mimetype

    def render(self, request):
        request.setHeader('Content-Type', self.mimetype)
        return self.data
