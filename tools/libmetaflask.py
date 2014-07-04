import os
import re
import errno
import hashlib

from weakref import ref as weakref
from werkzeug.datastructures import Headers
from werkzeug.utils import cached_property


_member_re = re.compile(r'^(\d{4})_(.*?).txt$')
_kv_re = re.compile(r'^(.*?)\s*:\s*(.*?)$')


def _normpath(x):
    return os.path.normpath(os.path.realpath(x))


class _MetaViewContainer(object):

    def __init__(self, metaview):
        self._metaview = weakref(metaview)

    @property
    def metaview(self):
        rv = self._metaview()
        if rv is not None:
            return rv
        raise AttributeError('Meta view went away')


def read_mime(f):
    headers = []
    h = hashlib.sha1()

    def _readline():
        line = f.readline()
        h.update(line)
        line = line.decode('utf-8')
        if not line.strip():
            return u''
        return line.rstrip('\r\n')

    while 1:
        line = _readline()
        if not line:
            break
        match = _kv_re.match(line)
        if match is not None:
            headers.append(match.groups())
            continue
        elif line[:1].isspace():
            old_key, old_value = headers[-1]
            headers[-1] = (old_key, old_value + u' ' + line[1:])
        else:
            raise ValueError('Invalid mime data')

    payload = f.read()
    h.update(payload)
    return Headers(headers), payload, h.hexdigest()


class Person(_MetaViewContainer):

    def __init__(self, metaview, path, f):
        _MetaViewContainer.__init__(self, metaview)
        self.path = _normpath(os.path.join(metaview.member_path, path))
        self.meta, payload, self.checksum = read_mime(f)
        self.description = payload.decode('utf-8').rstrip()

    @property
    def name(self):
        return self.meta.get('name')

    @property
    def twitter(self):
        return self.meta.get('twitter')

    @property
    def email(self):
        return self.meta.get('e-mail')

    def to_json(self, compact=False):
        return {
            'num': self.num,
            'login': self.login,
            'name': self.name,
            'twitter': self.twitter,
            'email': self.email,
            'description': self.description,
        }

    def __repr__(self):
        return '<Person %r>' % (
            self.name,
        )


class Member(Person):

    def __init__(self, metaview, path, num, login, f):
        Person.__init__(self, metaview, path, f)
        self.num = num
        self.login = login

    @cached_property
    def sponsor(self):
        sponsor = self.meta.get('sponsor')
        if sponsor not in (None, '', '<self>'):
            return self.metaview.members_by_login.get(sponsor)

    def to_json(self, compact=False):
        if compact:
            return {'num': self.num, 'login': self.login,
                    'name': self.name}
        rv = Person.to_json(self, compact=compact)
        if self.sponsor is None:
            rv['sponsor'] = None
        else:
            rv['sponsor'] = self.sponsor.to_json(compact=True)
        return rv

    def __repr__(self):
        return '<Member %04d: %r>' % (
            self.num,
            self.login,
        )


class ExtensionStatus(_MetaViewContainer):

    def __init__(self, metaview, f):
        _MetaViewContainer.__init__(self, metaview)
        self.meta = read_mime(f)[0]

    @property
    def is_approved(self):
        return self.meta.get('approved') == 'yes'

    def to_json(self):
        return {
            'is_approved': self.is_approved,
        }

    def __repr__(self):
        return '<ExtensionStatus %r>' % (
            self.meta,
        )


class Project(_MetaViewContainer):

    def __init__(self, metaview, filename):
        _MetaViewContainer.__init__(self, metaview)
        self.short_name = filename

    @property
    def path(self):
        return os.path.join(self.metaview.projects_path, self.short_name)

    @cached_property
    def meta(self):
        try:
            with open(os.path.join(self.path, 'META'), 'rb') as f:
                return read_mime(f)[0]
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
            return Headers()

    @property
    def name(self):
        return self.meta.get('name')

    @property
    def website(self):
        return self.meta.get('website')

    @property
    def github(self):
        return self.meta.get('github')

    @property
    def bugtracker(self):
        return self.meta.get('bugtracker')

    @property
    def documentation(self):
        return self.meta.get('documentation')

    @property
    def pypi(self):
        return self.meta.get('pypi')

    @property
    def license(self):
        return self.meta.get('license')

    @property
    def status(self):
        return self.meta.get('status')

    @cached_property
    def readme(self):
        for choice in 'README.rst', 'README.md', 'README':
            try:
                with open(os.path.join(self.path, choice), 'rb') as f:
                    return f.read().decode('utf-8').rstrip()
            except IOError:
                pass

    @cached_property
    def extension_status(self):
        try:
            with open(os.path.join(
                    self.path, 'EXTENSION_STATUS'), 'rb') as f:
                return ExtensionStatus(self.metaview, f)
        except IOError:
            pass

    @property
    def is_extension(self):
        return self.extension_status is not None

    @cached_property
    def project_lead(self):
        p = os.path.join(self.path, 'PROJECT_LEAD')
        if not os.path.exists(p):
            return
        rv = self.metaview.locate_linked_member(
            os.path.join(self.path, 'PROJECT_LEAD'))
        if rv is None:
            with open(p, 'rb') as f:
                rv = Person(self.metaview, p, f)
        return rv

    @cached_property
    def stewards(self):
        p = os.path.join(self.path, 'stewardship')
        try:
            files = os.listdir(p)
        except OSError:
            return ()
        rv = []
        for filename in files:
            mem = self.metaview.locate_linked_member(os.path.join(p, filename))
            if mem is not None:
                rv.append(mem)
        return tuple(rv)

    def to_json(self):
        return {
            'short_name': self.short_name,
            'name': self.name,
            'website': self.website,
            'github': self.github,
            'bugtracker': self.bugtracker,
            'documentation': self.documentation,
            'pypi': self.pypi,
            'license': self.license,
            'status': self.status,
            'readme': self.readme,
            'extension_status': self.extension_status
                and self.extension_status.to_json() or None,
            'is_extension': self.is_extension,
            'project_lead': self.project_lead
                and self.project_lead.to_json(compact=True) or None,
            'stewards': [x.to_json(compact=True) for x in self.stewards],
        }

    def __repr__(self):
        return '<Project %r>' % (
            self.short_name,
        )


def read_members(metaview):
    rv = []
    for filename in os.listdir(metaview.member_path):
        match = _member_re.match(filename)
        if match is None:
            continue
        if isinstance(filename, bytes):
            filename = filename.decode('utf-8')
        num, login = match.groups()
        with open(os.path.join(metaview.member_path, filename), 'rb') as f:
            rv.append(Member(metaview, filename, int(num), login, f))
    rv.sort(key=lambda x: x.num)
    return rv


def read_projects(metaview):
    rv = []
    for filename in os.listdir(metaview.projects_path):
        if filename[:1] == '.':
            continue
        if os.path.isdir(os.path.join(metaview.projects_path, filename)):
            rv.append(Project(metaview, filename))
    return rv


class MetaView(object):

    def __init__(self, path):
        self.path = path

        self.members_by_num = {}
        self.members_by_login = {}
        self.members_by_checksum = {}
        self.members_by_path = {}

        for mem in read_members(self):
            self.members_by_num[mem.num] = mem
            self.members_by_login[mem.login] = mem
            self.members_by_checksum[mem.checksum] = mem
            self.members_by_path[mem.path] = mem

        self.projects = {}
        for proj in read_projects(self):
            self.projects[proj.short_name] = proj

    def to_json(self):
        return {
            'members': [x.to_json() for x in self.iter_members()],
            'projects': [x.to_json() for x in self.iter_projects()],
        }

    def iter_members(self):
        return (x[1] for x in sorted(self.members_by_num.items()))

    def iter_projects(self):
        return self.projects.values()

    def locate_linked_member(self, path):
        npath = _normpath(path)
        try:
            lpath = _normpath(os.path.join(os.path.dirname(path),
                                           os.readlink(path)))
            rv = self.members_by_path.get(lpath)
            if rv is not None:
                return rv
        except OSError:
            pass

        try:
            with open(npath, 'rb') as f:
                checksum = hashlib.sha1(f.read()).hexdigest()
                return self.members_by_checksum.get(checksum)
        except IOError:
            pass

    @property
    def member_path(self):
        return os.path.join(self.path, 'members')

    @property
    def projects_path(self):
        return os.path.join(self.path, 'projects')


if __name__ == '__main__':
    import json
    mv = MetaView(os.path.join(os.path.dirname(__file__), '..'))
    print(json.dumps(mv.to_json(), indent=2))
