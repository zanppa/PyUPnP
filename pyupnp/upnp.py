from SOAPpy import parseSOAPRPC, buildSOAP
from twisted.internet import reactor
from twisted.web.error import UnsupportedMethod
from twisted.web.resource import Resource
from twisted.web.server import Site

__author__ = 'Dean Gardiner'


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

        print "[UPnP] listen()"
        self.site = Site(self)
        self.site_port = reactor.listenTCP(0, self.site, interface=interface)
        self.listen_address = self.site_port.socket.getsockname()[0]
        self.listen_port = self.site_port.socket.getsockname()[1]
        self.running = True

        self.device.location = "http://%s:" + str(self.listen_port)

        print "[UPnP] listening on", self.listen_address + ":" + str(self.listen_port)

    def stop(self):
        if not self.running:
            return

        print "[UPnP] stop()"
        self.site_port.stopListening()
        self.running = False

    def getChild(self, path, request):
        if path == '':
            return ServeResource(self.device.dumps(), 'application/xml')

        for service in self.device.services:
            if path == service.serviceId:
                return ServiceResource(service)

        print "[UPnP] unhandled request", path
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

        print "[UPnP][" + str(self.service.serviceType) + "] unhandled request", path
        return Resource()


class ServiceControlResource(Resource):
    def __init__(self, service):
        Resource.__init__(self)
        self.service = service

    def render(self, request):
        try:
            return Resource.render(self, request)
        except UnsupportedMethod, e:
            print "[UPnP][" + str(self.service.serviceType) + "] unhandled method", \
                request.method
            raise e

    def render_POST(self, request):
        data = request.content.getvalue()
        (r, header, body, attrs) = parseSOAPRPC(data, header=1, body=1, attrs=1)

        name = r._name
        kwargs = r._asdict()

        print "[UPnP][" + str(self.service.serviceType) + "]", name

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

        result = func(**kwargs)

        return buildSOAP(kw={
            '%sResponse' % name: result
        })


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
        except UnsupportedMethod, e:
            print "[UPnP][" + str(self.service.serviceType) + "] unhandled method",\
                request.method
            raise e

    def render_SUBSCRIBE(self, request):
        print "[UPnP][" + str(self.service.serviceType) + "][Event] SUBSCRIBE"

        if request.requestHeaders.hasHeader('sid'):
            # Renew
            raise NotImplementedError()
        else:
            # New Subscription
            nt = self._parse_nt(getHeader(request, 'nt'))
            callback = self._parse_callback(getHeader(request, 'callback'))
            timeout = self._parse_timeout(getHeader(request, 'timeout', False))

            print "[UPnP][" + str(self.service.serviceType) + "][Event]", callback, timeout

            responseHeaders = self.service.subscribe(callback, timeout)
            if responseHeaders is not None and type(responseHeaders) is dict:
                for name, value in responseHeaders.items():
                    request.setHeader(name, value)
                return ''
            else:
                print "[UPnP][" + str(self.service.serviceType) + "][Event] SUBSCRIBE FAILED"


class ServeResource(Resource):
    def __init__(self, data, mimetype):
        Resource.__init__(self)
        self.data = data
        self.mimetype = mimetype

    def render(self, request):
        request.setHeader('Content-Type', self.mimetype)
        return self.data
