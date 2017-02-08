import re
from lxml import etree
from lxml.builder import E


class _RpcMetaExec(object):

    # -----------------------------------------------------------------------
    # CONSTRUCTOR
    # -----------------------------------------------------------------------

    def __init__(self, junos):
        """
          ~PRIVATE CLASS~
          creates an RPC meta-executor object bound to the provided
          ez-netconf :junos: object
        """
        self._junos = junos

    # -----------------------------------------------------------------------
    # get_config
    # -----------------------------------------------------------------------

    def get_config(self, filter_xml=None, options={}, model=None, **kwargs):
        """
        retrieve configuration from the Junos device

        For example::
            dev.rpc.get_config()
            dev.rpc.get_config(model='openconfig')
            dev.rpc.get_config(filter_xml=etree.XML('<system><services/></system>'), options={'format': 'json'})
            dev.rpc.get_config(filter_xml=etree.XML('<bgp><neighbors></neighbors></bgp>'), model='openconfig')
            dev.rpc.get_config(filter_xml=etree.XML('<bgp/>'), model='openconfig')
            dev.rpc.get_config(filter_xml='<system><services/></system>')
            dev.rpc.get_config(filter_xml='system/services')

        :filter_xml: fully XML formatted tag which defines what to retrieve,
                     when omitted the entire configuration is returned;
                     the following returns the device host-name configured with "set system host-name":

        config = dev.rpc.get_config(filter_xml=etree.XML('<configuration><system><host-name/></system></configuration>'))

        :options: is a dictionary of XML attributes to set within the <get-configuration> RPC;
                  the following returns the device host-name either configured with "set system host-name"
                  and if unconfigured, the value inherited from apply-group re0|re1, typical for multi-RE systems:

        config = dev.rpc.get_config(filter_xml=etree.XML('<configuration><system><host-name/></system></configuration>'),
                 options={'database':'committed','inherit':'inherit'})

        :model: Can provide yang model openconfig/custom

        """

        nmspaces = {'openconfig': "http://openconfig.net/yang/",
                    'custom': "http://yang.juniper.net/customyang/"}

        rpc = E('get-configuration', options)

        if filter_xml is not None:
            if not isinstance(filter_xml, etree._Element):
                if re.search("^<.*>$", filter_xml):
                    filter_xml = etree.XML(filter_xml)
                else:
                    filter_data = None
                    for tag in filter_xml.split('/')[::-1]:
                        filter_data = E(tag) if filter_data is None else E(
                            tag,
                            filter_data)
                    filter_xml = filter_data
            # wrap the provided filter with toplevel <configuration> if
            # it does not already have one (not in case of yang model config)
            if filter_xml.tag != 'configuration' and not nmspaces.get(model):
                etree.SubElement(rpc, 'configuration').append(filter_xml)
            else:
                if model is not None:
                    ns = nmspaces.get(model.lower())
                    filter_xml.attrib['xmlns'] = ns + filter_xml.tag
                rpc.append(filter_xml)
        response = self._junos.execute(rpc, **kwargs)
        # in case of model provided top level should be rpc-reply or data??
        return response if model is None else response.getparent()

    # -----------------------------------------------------------------------
    # get
    # -----------------------------------------------------------------------

    def get(self, filter_select=None, **kwargs):
        """
        Retrieve running configuration and device state information using
        <get> rpc

        For example::
          dev.rpc.get()
          or
          dev.rpc.get(ignore_warning=True)
          or
          dev.rpc.get(filter_select='bgp') or dev.rpc.get('bgp')
          or
          dev.rpc.get(filter_select='bgp/neighbors')
          dev.rpc.get("/bgp/neighbors/neighbor[neighbor-address='10.10.0.1']/timers/state/hold-time")

        :param str filter_select:
          The select attribute will be treated as an XPath expression and
          used to filter the returned data.

        :returns: xml object
        """
        # junos only support filter type to be xpath
        filter_params = {'type': 'xpath'}
        if filter_select is not None:
            filter_params['source'] = filter_select
        rpc = E('get', E('filter', filter_params))
        return self._junos.execute(rpc, **kwargs)

    # -----------------------------------------------------------------------
    # load_config
    # -----------------------------------------------------------------------

    def load_config(self, contents, **options):
        """
        loads :contents: onto the Junos device, does not commit the change.

        :options: is a dictionary of XML attributes to set within the <load-configuration> RPC.

        The :contents: are interpreted by the :options: as follows:

        format='text' and action='set', then :contents: is a string containing a series of "set" commands

        format='text', then :contents: is a string containing Junos configuration in curly-brace/text format

        format='json', then :contents: is a string containing Junos configuration in json format

        <otherwise> :contents: is XML structure
        """
        rpc = E('load-configuration', options)

        if ('action' in options) and (options['action'] == 'set'):
            rpc.append(E('configuration-set', contents))
        elif ('format' in options) and (options['format'] == 'text'):
            rpc.append(E('configuration-text', contents))
        elif ('format' in options) and (options['format'] == 'json'):
            rpc.append(E('configuration-json', contents))
        else:
            # otherwise, it's just XML Element
            if contents.tag != 'configuration':
                etree.SubElement(rpc, 'configuration').append(contents)
            else:
                rpc.append(contents)

        return self._junos.execute(rpc)

    # -----------------------------------------------------------------------
    # cli
    # -----------------------------------------------------------------------

    def cli(self, command, format='text', normalize=False):
        rpc = E('command', command)
        if format.lower() in ['text', 'json']:
            rpc.attrib['format'] = format
        return self._junos.execute(rpc, normalize=normalize)

    # -----------------------------------------------------------------------
    # method missing
    # -----------------------------------------------------------------------

    def __getattr__(self, rpc_cmd_name):
        """
          metaprograms a function to execute the :rpc_cmd_name:

          the caller will be passing (*vargs, **kvargs) on
          execution of the meta function; these are the specific
          rpc command arguments(**kvargs) and options bound
          as XML attributes (*vargs)
        """

        rpc_cmd = re.sub('_', '-', rpc_cmd_name)

        def _exec_rpc(*vargs, **kvargs):
            # create the rpc as XML command
            rpc = etree.Element(rpc_cmd)

            # kvargs are the command parameter/values
            if kvargs:
                for arg_name, arg_value in kvargs.items():
                    if arg_name not in ['dev_timeout', 'normalize']:
                        arg_name = re.sub('_', '-', arg_name)
                        if isinstance(arg_value, (tuple, list)):
                            for a in arg_value:
                                arg = etree.SubElement(rpc, arg_name)
                                if a is not True:
                                    arg.text = a
                        else:
                            arg = etree.SubElement(rpc, arg_name)
                            if arg_value is not True:
                                arg.text = arg_value

            # vargs[0] is a dict, command options like format='text'
            if vargs:
                for k, v in vargs[0].items():
                    if v is not True:
                        rpc.attrib[k] = v

            # gather any decorator keywords
            timeout = kvargs.get('dev_timeout')
            normalize = kvargs.get('normalize')

            dec_args = {}

            if timeout is not None:
                dec_args['dev_timeout'] = timeout
            if normalize is not None:
                dec_args['normalize'] = normalize

            # now invoke the command against the
            # associated :junos: device and return
            # the results per :junos:execute()
            return self._junos.execute(rpc, **dec_args)

        # metabind help() and the function name to the :rpc_cmd_name:
        # provided by the caller ... that's about all we can do, yo!

        _exec_rpc.__doc__ = rpc_cmd
        _exec_rpc.__name__ = rpc_cmd_name

        # return the metafunction that the caller will in-turn invoke
        return _exec_rpc

    # -----------------------------------------------------------------------
    # callable
    # -----------------------------------------------------------------------

    def __call__(self, rpc_cmd, **kvargs):
        """
          callable will execute the provided :rpc_cmd: against the
          attached :junos: object and return the RPC response per
          :junos:execute()

          kvargs is simply passed 'as-is' to :junos:execute()
        """
        return self._junos.execute(rpc_cmd, **kvargs)
