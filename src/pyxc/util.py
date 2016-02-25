#  -*- coding: utf-8 -*-
#
import ast
import copy
import json
import inspect
import itertools
import random
import re
import subprocess
import sys
import tempfile
import traceback

import sourcemaps


def simplePost(url, POST={}):
    try:
        import urllib.parse, urllib.request
        data = urllib.parse.urlencode(POST)
        return urllib.request.urlopen(url, data).read()
    except ImportError:
        import urllib, urllib2
        data = urllib.urlencode(POST)
        return urllib2.urlopen(urllib2.Request(url, data)).read()


def delimited(delimiter, arr, dest=None, at_end=False):
    if dest is None:
        dest = []
    if arr:
        dest.append(arr[0])
    for i in range(1, len(arr)):
        dest.append(delimiter)
        dest.append(arr[i])
    if at_end:
        dest.append(delimiter)
    return dest


def usingPython3():
    return sys.version_info[0] == 3


def parentOf(path):
    return '/'.join(path.rstrip('/').split('/')[:-1])


def body_top_names(body):
    names = set()
    for x in body:
        names |= node_names(x)
    return names


def controlled_ast_walk(node):
    """Walk ast just like ast.walk(), but expect True on every branch to
    descend on sub-branches."""
    l = [node]
    while len(l) > 0:
        popped = l.pop()
        check_children = (yield popped)
        if check_children:
            for n in ast.iter_child_nodes(popped):
                l.append(n)


def body_local_names(body):
    """Find the names assigned to in the provided body. It doesn't descent
    into function or class subelements."""
    names = set()
    for node in body:
        it = controlled_ast_walk(node)
        try:
            while True:
                subn = next(it)
                names |= node_names(subn)
                if not isinstance(subn, (ast.FunctionDef, ast.ClassDef,
                                         ast.AsyncFunctionDef)):
                    it.send(True) # continue traversing sub names
        except StopIteration:
            pass
    return names


def node_names(x):
    names = set()
    if isinstance(x, ast.Assign):
        for target in x.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    elif isinstance(x, (ast.FunctionDef, ast.ClassDef)):
        names.add(x.name)
    return names



def exceptionRepr(exc_info=None):

    if usingPython3():
        from io import StringIO
    else:
        from StringIO import StringIO

    if not exc_info:
        exc_info = sys.exc_info()
    f = StringIO()
    traceback.print_exception(exc_info[0], exc_info[1], exc_info[2], file=f)
    return f.getvalue()


# Write a JSON representation of the exception to stderr for
# the script that's invoking us (e.g. pj.api under Python 2)
def writeExceptionJsonAndDie(e):
    sys.stderr.write('%s\n' % json.dumps({
        'name': e.__class__.__name__,
        'message': exceptionRepr(),
    }))
    sys.exit(1)


def randomToken(n):
    while True:
        token = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz') for i in range(n))
        if not token.isdigit():
            return token


class CyclicGraphError(Exception): pass


class DirectedGraph:

    def __init__(self):
        self._graph = {}

    def addNode(self, x):
        if x not in self._graph:
            self._graph[x] = set()

    def addArc(self, x, y):
        self.addNode(x)
        self.addNode(y)
        self._graph[x].add(y)

    @property
    def topologicalOrdering(self):

        def topologicalOrderingDestructive(d):

            if len(d) == 0:
                return []

            possibleInitialNodes = set(d.keys())
            for k, v in d.items():
                if len(v) > 0:
                    possibleInitialNodes.discard(k)
            if len(possibleInitialNodes) == 0:
                raise CyclicGraphError(repr(d))
            initialNode = possibleInitialNodes.pop()

            for k, v in d.items():
                v.discard(initialNode)
            del d[initialNode]

            return [initialNode] + topologicalOrderingDestructive(d)

        return topologicalOrderingDestructive(copy.deepcopy(self._graph))


def rfilter(r, it, propFilter={}, invert=False):
    '''

    >>> list(rfilter(r'^.o+$', ['foo', 'bar']))
    ['foo']

    >>> list(rfilter(r'^.o+$', ['foo', 'bar'], invert=True))
    ['bar']

    >>> list(rfilter(r'-(?P<x>[^-]+)-', ['fooo-baar-ooo', 'fooo-fooo-ooo'], propFilter={'x': r'o{3}'}))
    ['fooo-fooo-ooo']

    >>> list(rfilter(r'-(?P<x>[^-]+)-', ['fooo-.*-ooo', 'fooo-fooo-ooo', 'fooo-.+-ooo'], propFilter={'x': ['.*', '.+']}))
    ['fooo-.*-ooo', 'fooo-.+-ooo']

    '''

    # Supports Python 2 and 3
    if isinstance(r, str):
        r = re.compile(r)
    try:
        if isinstance(r, unicode):
            r = re.compile
    except NameError:
        pass

    for x in it:
        m = r.search(x)
        ok = False
        if m:
            ok = True
            if propFilter:
                d = m.groupdict()
                for k, v in propFilter.items():
                    if k in d:
                        if isinstance(v, basestring):
                            if not re.search(v, d[k]):
                                ok = False
                                break
                        else:
                            if d[k] not in v:
                                ok = False
                                break

        if invert:
            if not ok:
                yield x
        else:
            if ok:
                yield x


class SubprocessError(Exception):

    def __init__(self, out, err, returncode):
        self.out = out
        self.err = err
        self.returncode = returncode
        self.msg = repr('--- out ---\n%s\n--- err ---\n%s\n--- code: %d ---' % (self.out, self.err, self.returncode))


def communicateWithReturncode(cmd, input=None, **Popen_kwargs):
    if input is not None:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, **Popen_kwargs)
        (out, err) = p.communicate(input=input)
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **Popen_kwargs)
        (out, err) = p.communicate()
    return out, err, p.returncode


def communicate(cmd, assertZero=False, input='', **Popen_kwargs):
    out, err, returncode = communicateWithReturncode(cmd, input=input, **Popen_kwargs)
    return (out, err)


def check_communicate(cmd, input='', **Popen_kwargs):
    out, err, returncode = communicateWithReturncode(cmd, input=input, **Popen_kwargs)
    if returncode != 0:
        raise SubprocessError(out, err, returncode)
    return (out, err)


class TempDir:

    def __init__(self):
        self.path = tempfile.mkdtemp()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        subprocess.check_call(['rm', '-rf', self.path])


class OutputSrc:

    def __init__(self, node):
        self.node = node

    def _gen_mapping(self, text, src_line=None, src_offset=None, dst_offset=None):
        """Generate a single mapping. `dst_line` is absent from signature
        because the part hasn't this information, but is present in the
        returned mapping. `src_line` is adjusted to be 0-based.

        See `Source Map version 3 proposal
        <https://docs.google.com/document/d/1U1RGAehQwRypUTovF1KRlpiOFze0b-_2gc6fAH0KY0k>`_.
        """
        return {
            'src_line': src_line - 1 if src_line else None,
            'src_offset': src_offset,
            'dst_line': None,
            'dst_offset': dst_offset,
            'text': text
        }

    def _pos_in_src(self):
        """Returns the position in source of the generated node"""
        py_node = self.node.py_node
        if py_node:
            result = (getattr(py_node, 'lineno', None),
                      getattr(py_node, 'col_offset', None))
        else:
            result = (None, None)
        return result



class Line(OutputSrc):

    def __init__(self, node, item, indent=False, delim=False):
        super().__init__(node)
        self.indent = int(indent)
        self.delim = delim
        if isinstance(item, (tuple, list)):
            item = Part(node, *item)
        self.item = item

    def __str__(self):
        line = str(self.item)
        if self.delim:
            line += ';'
        if self.indent:
            line = (' ' * 4 * self.indent) + line
        line += '\n'
        return line

    def serialize(self):
        yield self

    def src_mappings(self):
        src_line, src_offset = self._pos_in_src()
        offset = self.indent * 4
        if isinstance(self.item, str) and src_line:
            yield self._gen_mapping(self.item, src_line, src_offset, offset)
        else:
            assert isinstance(self.item, Part)
            for m in self.item.src_mappings():
                m['dst_offset'] += offset
                yield m

    def __repr__(self):
        return '<%s indent: %d, "%s">' % (self.__class__.__name__,
                                          self.indent, str(self))

class Part(OutputSrc):

    def __init__(self, node, *items):
        super().__init__(node)
        self.items = []
        for i in items:
            if isinstance(i, (str, Part)):
                self.items.append(i)
            elif inspect.isgenerator(i):
                self.items.extend(i)
            else:
                raise ValueError

    def __str__(self):
        return ''.join(str(i) for i in self.items)

    def serialize(self):
        yield self

    def src_mappings(self):
        src = str(self)
        src_line, src_offset = self._pos_in_src()
        frag = ''
        col = 0
        for i in self.items:
            if isinstance(i, str):
               frag += i
            elif isinstance(i, Part):
                if frag and src_line:
                    yield self._gen_mapping(frag, src_line, src_offset, col)
                    frag = ''
                psrc = str(i)
                col = src.find(psrc) + len(psrc)
                yield from i._translate_src_mappings(i, src, psrc)
            else:
                raise ValueError
        else:
            if frag and src_line:
                yield self._gen_mapping(frag, src_line, src_offset, col)

    def _translate_src_mappings(self, part, src=None, psrc=None):
        src = src or str(self)
        psrc = psrc or str(part)
        offset = src.find(psrc)
        for m in part.src_mappings():
            m['dst_offset'] += offset
            yield m

    def __repr__(self):
        return '<%s, "%s">' % (self.__class__.__name__,
                               str(self))

class Block(OutputSrc):

    def __init__(self, node):
        super().__init__(None)
        self.lines = list(node.serialize())

    def src_mappings(self):
        mappings = itertools.chain.from_iterable(map(lambda l: l.src_mappings(),
                                                     self.lines))
        for ix, m in enumerate(mappings, start=0):
            m['dst_line'] = ix
            yield m

    def read(self):
        return ''.join(str(l) for l in self.lines)

    def sourcemap(self, source, src_filename):
        Token = sourcemaps.Token
        tokens = [Token(m['dst_line'], m['dst_offset'], src_filename,
                        m['src_line'], m['src_offset']) for m in
                  self.src_mappings()]
        src_map = sourcemaps.SourceMap(
            #sources_content={src_filename: source}
        )
        for t in tokens:
            src_map.add_token(t)
        return sourcemaps.encode(src_map)
