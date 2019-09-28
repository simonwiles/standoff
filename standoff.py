"""
* Inspired by https://github.com/standoff-nlp/standoffconverter
"""

from functools import singledispatch
from operator import itemgetter, attrgetter

from lxml import etree


@singledispatch
def get_root_element(input_xml):
    raise TypeError("input_xml must be one of ElementTree, Element, string, or bytes!")


get_root_element.register(bytes, lambda xml_input: etree.fromstring(xml_input))
get_root_element.register(str, lambda xml_input: etree.fromstring(xml_input.encode('UTF-8')))
get_root_element.register(etree._Element, lambda xml_input: xml_input)
get_root_element.register(etree._ElementTree, lambda xml_input: xml_input.getroot())


def xml_safe(text):
    if text is None:
        return ''

    replacements = (
        ('&', '&amp;'),
        ('"', '&quot;'),
        ("'", '&apos;'),
        ('<', '&lt;'),
        ('>', '&gt;'),
    )
    for find, replace in replacements:
        text = text.replace(find, replace)

    return text


class StandoffDoc:

    def __init__(self, xml_input):

        self.standoffs = []
        self.root_element = get_root_element(xml_input)

        self.nsmap = self.root_element.nsmap
        self.reverse_nsmap = {value: key for key, value in self.nsmap.items()}
        self.xml_to_standoff()

        # from pprint import pprint
        # pprint(self.standoffs)

    def proc_ns(self, tag):
        if '}' not in tag:
            return tag
        ns, tagname = tag[1:].split('}')

        if ns == 'http://www.w3.org/XML/1998/namespace':
            # special case
            return f'xml:{tagname}'

        if self.reverse_nsmap[ns] is None:
            return tagname

        return f'{self.reverse_nsmap[ns]}:{tagname}'

    def xml_to_standoff(self):
        plain_text = []

        def parse_element(element, plain_text, depth=0):
            props = {
                'begin': len(plain_text),
                'tag': self.proc_ns(element.tag),
                'attrib': element.attrib,
                'depth': depth,
                'begin_sort': len([_ for _ in self.standoffs if _['begin'] == len(plain_text)])
            }

            plain_text.extend(xml_safe(element.text))

            for subelement in element:
                parse_element(subelement, plain_text, depth=depth + 1)

            props['end'] = len(plain_text)
            props['end_sort'] = len([_ for _ in self.standoffs if _['end'] == len(plain_text)])

            plain_text.extend(xml_safe(element.tail))
            depth -= 1

            self.standoffs.append(props)

        parse_element(self.root_element, plain_text)

        self.plain_text = ''.join(plain_text)

    def to_xml(self):
        """create a standoff representation from an lxml tree.

        returns:
        string -- the string containing the xml
        """

        # for every index in plain_text (plus one for the end), we need a list of elements
        #  that begin at that index, and a list of those that end there.
        standoff_begin_lookup = [[] for _ in self.plain_text] + [[]]
        standoff_end_lookup = [[] for _ in self.plain_text] + [[]]
        standoff_empty_lookup = [[] for _ in self.plain_text] + [[]]

        for standoff in self.standoffs:
            if standoff['begin'] == standoff['end']:
                standoff_empty_lookup[standoff['begin']] += [standoff]
                continue

            standoff_begin_lookup[standoff['begin']] += [standoff]
            standoff_end_lookup[standoff['end']] += [standoff]

        def render_empty_tags(idx):
            sorted_empty = sorted(standoff_empty_lookup[idx], key=itemgetter('depth'))
            return ''.join(
                f'<{standoff["tag"] + render_attribs(standoff["attrib"])}/>'
                for standoff in sorted_empty)

        def render_opening_tags(idx):
            # sorted_begin = sorted(
            #     sorted(standoff_begin_lookup[idx], key=itemgetter('depth')),
            #     key=lambda standoff: -(standoff['end'] - standoff['begin'])
            # )
            sorted_begin = sorted(standoff_begin_lookup[idx], key=itemgetter('depth'))
            return ''.join(
                f'<{standoff["tag"] + render_attribs(standoff["attrib"])}>'
                for standoff in sorted_begin)


        def render_closing_tags(idx):
            # sorted_closing_tags = sorted(
            #     sorted(
            #         standoff_end_lookup[idx],
            #         key=lambda standoff: -(standoff['end'] - standoff['begin'])),
            #     key=itemgetter('depth'), reverse=True)
            sorted_closing_tags = sorted(
                standoff_end_lookup[idx],
                key=itemgetter('depth'), reverse=True
            )
            return ''.join(f'</{standoff["tag"]}>' for standoff in sorted_closing_tags)


        def render_attribs(attribs):
            if not attribs:
                return ''
            return (' ' +
                    ' '.join(f'{self.proc_ns(key)}="{value}"' for key, value in attribs.items()))

        def render_tags(idx):
            all_standoffs = (
                sorted(standoff_end_lookup[idx], key=itemgetter('depth'), reverse=True) +
                sorted(standoff_empty_lookup[idx] + standoff_begin_lookup[idx], key=itemgetter('depth'))
            )

            # if an empty tag follows a closing tag _and_ has a greater depth...
            # except relying on the order in self.standoffs will cause a problem when tags are
            #  inserted (or removed...)

            all_standoffs.sort(key=lambda standoff: standoff.get('begin_sort', 0) if standoff['begin'] == idx else standoff.get('end_sort', 0))
            # all_standoffs.sort(key=lambda standoff: self.standoffs.index(standoff))

            # if all_standoffs:
            #     from pprint import pprint
            #     pprint(all_standoffs)
            ret = []
            for standoff in all_standoffs:
                if standoff["begin"] == idx and standoff["end"] == idx:
                    # self-closing
                    ret.append(f'<{standoff["tag"] + render_attribs(standoff["attrib"])}/>')
                elif standoff["begin"] == idx:
                    # opening
                    ret.append(f'<{standoff["tag"] + render_attribs(standoff["attrib"])}>')
                elif standoff["end"] == idx:
                    # closing
                    ret.append(f'</{standoff["tag"]}>')
            return ''.join(ret)

        out_xml = ''.join(
            # (render_closing_tags(idx) + render_empty_tags(idx) + render_opening_tags(idx) + char)
            (render_tags(idx) + char)
            for idx, char in enumerate(self.plain_text))

        out_xml += render_closing_tags(-1)

        # return out_xml
        return etree.tostring(etree.fromstring(out_xml), pretty_print=True, encoding='unicode')

    def add_annotation(self, begin, end, tag, depth, attribute, unique=True):
        """add a standoff annotation.

        arguments:
        begin (int) -- the beginning character index
        end (int) -- the ending character index
        tag (str) -- the name of the xml tag
        depth (int) -- tree depth of the attribute. for the same begin and end,
                 a lower depth annotation includes a higher depth annotation
        attribute (dict) -- attrib of the lxml

        keyword arguments:
        unique (bool) -- whether to allow for duplicate annotations
        """
        if not unique or not self.is_duplicate_annotation(begin, end, tag, attribute):
            self.standoffs.append({
                "begin": begin,
                "end": end,
                "tag": tag,
                "attrib": attribute,
                "depth": depth if depth is not None else 0
            })

    def is_duplicate_annotation(self, begin, end, tag, attribute):
        """check whether this annotation already in self.standoffs

        arguments:
        begin (int) -- the beginning character index
        end (int) -- the ending character index
        tag (str) -- the name of the xml tag
        attribute (dict) -- attrib of the lxml

        returns:
        bool -- True if annotation already exists
        """

        def attrs_equal(attr_a, attr_b):
            shared_items = {}
            for k in attr_a:
                if k in attr_b and attr_a[k] == attr_b[k]:
                    shared_items[k] = attr_a[k]

            return len(attr_a) == len(attr_b) == len(shared_items)

        for standoff in self.standoffs:
            if (standoff["begin"] == begin
                and standoff["end"] == end
                and standoff["tag"] == tag
                and attrs_equal(attribute, standoff["attrib"])):
                return True
        return False
