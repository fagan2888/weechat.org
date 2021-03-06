# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2020 Sébastien Helleu <flashcode@flashtux.org>
#
# This file is part of WeeChat.org.
#
# WeeChat.org is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# WeeChat.org is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with WeeChat.org.  If not, see <https://www.gnu.org/licenses/>.
#

"""Models for "scripts" menu."""

import gzip
import hashlib
import json
import os
import re
from collections import OrderedDict
from io import open
from xml.sax.saxutils import escape

from django import forms
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models.signals import pre_save, post_save, post_delete
from django.utils import translation
from django.utils.translation import ugettext, ugettext_lazy, pgettext_lazy

from weechat.common.decorators import disable_for_loaddata
from weechat.common.forms import (
    BootstrapBoundField,
    CharField,
    ChoiceField,
    EmailField,
    FileField,
    TestField,
    Html5EmailInput,
    Form,
)
from weechat.common.i18n import i18n_autogen
from weechat.common.path import files_path_join
from weechat.download.models import Release

SCRIPT_LANGUAGE = {
    'python': ('py', 'python'),
    'perl': ('pl', 'perl'),
    'ruby': ('rb', 'ruby'),
    'lua': ('lua', 'lua'),
    'tcl': ('tcl', 'tcl'),
    'guile': ('scm', 'scheme'),
    'javascript': ('js', 'javascript'),
    'php': ('php', 'php'),
}

MAX_LENGTH_NAME = 32
MAX_LENGTH_VERSION = 32
MAX_LENGTH_URL = 512
MAX_LENGTH_LANGUAGE = 32
MAX_LENGTH_LICENSE = 32
MAX_LENGTH_MD5SUM = 32
MAX_LENGTH_SHA512SUM = 128
MAX_LENGTH_TAGS = 512
MAX_LENGTH_DESC = 1024
MAX_LENGTH_APPROVAL = 1024
MAX_LENGTH_DISABLED = 1024
MAX_LENGTH_REQUIRE = 512
MAX_LENGTH_AUTHOR = 256
MAX_LENGTH_MAIL = 256


def get_language_from_extension(ext):
    return next((key for key, value in SCRIPT_LANGUAGE.items()
                 if value[0] == ext), None)


class Script(models.Model):
    """A WeeChat script."""
    approved = models.BooleanField(default=False)
    popularity = models.IntegerField()
    name = models.CharField(max_length=MAX_LENGTH_NAME)
    version = models.CharField(max_length=MAX_LENGTH_VERSION)
    url = models.CharField(max_length=MAX_LENGTH_URL, blank=True)
    language = models.CharField(max_length=MAX_LENGTH_LANGUAGE)
    license = models.CharField(max_length=MAX_LENGTH_LICENSE)
    md5sum = models.CharField(max_length=MAX_LENGTH_MD5SUM, blank=True)
    sha512sum = models.CharField(max_length=MAX_LENGTH_SHA512SUM, blank=True)
    tags = models.CharField(max_length=MAX_LENGTH_TAGS, blank=True)
    desc_en = models.CharField(max_length=MAX_LENGTH_DESC)
    approval = models.CharField(max_length=MAX_LENGTH_APPROVAL, blank=True)
    disabled = models.CharField(max_length=MAX_LENGTH_DISABLED, blank=True)
    requirements = models.CharField(max_length=MAX_LENGTH_REQUIRE, blank=True)
    min_weechat = models.CharField(max_length=MAX_LENGTH_VERSION, blank=True)
    max_weechat = models.CharField(max_length=MAX_LENGTH_VERSION, blank=True)
    author = models.CharField(max_length=MAX_LENGTH_AUTHOR)
    mail = models.EmailField(max_length=MAX_LENGTH_MAIL)
    added = models.DateTimeField()
    updated = models.DateTimeField(null=True)

    def __str__(self):
        return '%s %s (%s, %s)%s%s' % (
            self.name,
            self.version,
            self.author,
            self.added,
            '' if self.approved else ' [pending]',
            ' [DISABLED]' if self.disabled else '',
        )

    def __unicode__(self):  # python 2.x
        return self.__str__()

    def tagslist(self):
        """Return a list with script tags."""
        return self.tags.split(',')

    def is_py2_ok(self):
        """
        Return True if the script is a Python script compatible with
        Python 2.x.
        """
        return 'py2' in self.tagslist()

    def is_py3_ok(self):
        """
        Return True if the script is a Python script compatible with
        Python 3.x.
        """
        return 'py3' in self.tagslist()

    def path(self):
        """Return path to script (for URL)."""
        return 'scripts' if self.approved else 'scripts/pending'

    def popularity_img(self):
        """Return HTML code with image for popular script."""
        if self.popularity == 0:
            return ('<img src="%simages/empty.png" alt="" '
                    'width="10" height="10">' % settings.MEDIA_URL)
        return ('<img src="%simages/star.png" alt="*" title="%s" '
                'width="10" height="10">' %
                (settings.MEDIA_URL,
                 ugettext('Popular script')))

    def name_with_extension(self):
        """Return the name of script with its extension."""
        return '%s.%s' % (self.name, SCRIPT_LANGUAGE[self.language][0])

    def extension(self):
        """Return script extension."""
        return SCRIPT_LANGUAGE[self.language][0]

    def language_display(self):
        """Return script language."""
        return SCRIPT_LANGUAGE[self.language][1]

    def desc_i18n(self):
        """Return translated description."""
        if not isinstance(self.desc_en, str):
            # python 2.x
            return ugettext(self.desc_en.encode('utf-8'))
        return ugettext(self.desc_en)

    def disabled_i18n(self):
        """Return the translated disabled reason."""
        if not isinstance(self.disabled, str):
            # python 2.x
            return ugettext(self.disabled.encode('utf-8'))
        return ugettext(self.disabled)

    def version_weechat(self):
        """Return the WeeChat supported versions in a string."""
        return '%s+' % (self.min_weechat or '0.3.0')

    def version_weechat_html(self):
        """Return the WeeChat supported versions in a string for HTML."""
        return '&ge; %s' % (self.min_weechat or '0.3.0')

    def build_url(self):
        """Return URL to the script."""
        return '/files/%s/%s' % (self.path(), self.name_with_extension())

    def filename(self):
        """Return script filename (on disk)."""
        return files_path_join(self.path(),
                               os.path.basename(self.name_with_extension()))

    def file_exists(self):
        """Check if script exists (on disk)."""
        return os.path.isfile(self.filename())

    def checksum(self, hash_func):
        """Return script checksum using the hash function (from hashlib)."""
        try:
            with open(self.filename(), 'rb') as _file:
                return hash_func(_file.read()).hexdigest()
        except:  # noqa: E722
            return ''

    def get_md5sum(self):
        """
        Return the script MD5 (if known), or compute it with the file
        if it is not set in database.
        """
        return self.md5sum or self.checksum(hashlib.md5)

    def get_sha512sum(self):
        """
        Return the script SHA512 (if known), or compute it with the file
        if it is not set in database.
        """
        return self.sha512sum or self.checksum(hashlib.sha512)

    class Meta:
        ordering = ['-added']


class NameField(forms.CharField):
    """Name field in new script form."""

    def clean(self, value):
        if not value:
            raise forms.ValidationError(
                ugettext('This field is required.'))
        if not re.search('^[a-z0-9_]+$', value):
            raise forms.ValidationError(
                ugettext('This name is invalid.'))
        scripts = Script.objects.filter(name=value)
        if scripts:
            raise forms.ValidationError(
                ugettext('This name already exists, please choose another '
                         'name (update script content accordingly).'))
        return value

    def get_bound_field(self, form, field_name):
        return BootstrapBoundField(form, self, field_name)


def get_min_weechat_choices():
    """Get min WeeChat versions for add form."""
    version_min = []
    try:
        devel_desc = Release.objects.get(version='devel').description
        releases = Release.objects.filter(
            version__gte='0.3.0',
            version__lte=re.sub('-.*', '', devel_desc)).order_by('date')
        for rel in releases:
            version = (
                rel.version,
                '≥ {}'.format(rel.version),
            )
            version_min.append(version)
    except ObjectDoesNotExist:
        version_min = []
    return version_min


class ScriptFormAdd(Form):
    """Form to add a script."""
    languages = (
        ('python', 'Python (.py)'),
        ('perl', 'Perl (.pl)'),
        ('ruby', 'Ruby (.rb)'),
        ('lua', 'Lua (.lua)'),
        ('tcl', 'Tcl (.tcl)'),
        ('guile', 'Scheme (.scm)'),
        ('javascript', 'Javascript (.js)'),
        ('php', 'PHP (.php)'),
    )
    required_css_class = 'required'
    language = ChoiceField(
        choices=languages,
        label=pgettext_lazy(u'The programming language.', u'Language'),
        widget=forms.Select(attrs={'autofocus': True}),
    )
    name = NameField(
        max_length=MAX_LENGTH_NAME,
        label=ugettext_lazy('Name'),
    )
    version = CharField(
        max_length=MAX_LENGTH_VERSION,
        label=ugettext_lazy('Version'),
        help_text=ugettext_lazy('The version of script '
                                '(only digits or dots).'),
    )
    license = CharField(
        max_length=MAX_LENGTH_LICENSE,
        label=ugettext_lazy('License'),
        help_text=ugettext_lazy('The license (for example: GPL3, BSD, etc.).'),
    )
    file = FileField(
        label=ugettext_lazy('File'),
        help_text=ugettext_lazy('The script.'),
    )
    description = CharField(
        max_length=MAX_LENGTH_DESC,
        label=ugettext_lazy('Description'),
    )
    requirements = CharField(
        required=False,
        max_length=MAX_LENGTH_REQUIRE,
        label=ugettext_lazy('Requirements'),
    )
    min_weechat = ChoiceField(
        choices=[],
        label=ugettext_lazy('Min WeeChat version.'),
    )
    author = CharField(
        max_length=MAX_LENGTH_AUTHOR,
        label=ugettext_lazy('Your name or nick'),
        help_text=ugettext_lazy('Used for git commit and scripts page.'),
    )
    mail = EmailField(
        max_length=MAX_LENGTH_MAIL,
        label=ugettext_lazy('Your e-mail'),
        help_text=ugettext_lazy('Used for git commit.'),
        widget=Html5EmailInput(),
    )
    comment = CharField(
        required=False,
        max_length=1024,
        label=ugettext_lazy('Comments'),
        help_text=ugettext_lazy('Not displayed.'),
        widget=forms.Textarea(attrs={'rows': '3'}),
    )
    test = TestField(
        max_length=64,
        label=ugettext_lazy('Are you a spammer?'),
        help_text=ugettext_lazy('Enter "no" if you are not a spammer.'),
    )

    def __init__(self, *args, **kwargs):
        super(ScriptFormAdd, self).__init__(*args, **kwargs)
        self.label_suffix = ''
        self.fields['min_weechat'].choices = get_min_weechat_choices()
        self.fields['name'].help_text = ugettext(
            'The short name of script (max {max_chars} chars, '
            'only lower case letters, digits or "_").').format(
                max_chars=MAX_LENGTH_NAME)


def get_script_choices():
    """Get list of scripts for update form."""
    try:
        script_list = Script.objects.filter(approved=True).order_by('name')
        script_choices = []
        script_choices.append(('', ugettext(u'Choose…')))
        for script in script_list:
            name = '%s - v%s (%s)' % (script.name_with_extension(),
                                      script.version, script.version_weechat())
            script_choices.append((script.id, name))
        return script_choices
    except:  # noqa: E722
        return []


class ScriptFormUpdate(Form):
    """Form to update a script."""
    required_css_class = 'required'
    script = ChoiceField(
        choices=[],
        label=ugettext_lazy('Script'),
        widget=forms.Select(attrs={'autofocus': True}),
    )
    version = CharField(
        max_length=MAX_LENGTH_VERSION,
        label=ugettext_lazy('New version'),
    )
    file = FileField(
        label=ugettext_lazy('File'),
        help_text=ugettext_lazy('The script.'),
    )
    author = CharField(
        max_length=MAX_LENGTH_AUTHOR,
        label=ugettext_lazy('Your name or nick'),
        help_text=ugettext_lazy('Used for git commit.'),
    )
    mail = EmailField(
        max_length=MAX_LENGTH_MAIL,
        label=ugettext_lazy('Your e-mail'),
        help_text=ugettext_lazy('Used for git commit.'),
        widget=Html5EmailInput(),
    )
    comment = CharField(
        max_length=1024,
        label=ugettext_lazy('Comments'),
        help_text=ugettext_lazy('Changes in this release.'),
        widget=forms.Textarea(attrs={'rows': '3'}),
    )
    test = TestField(
        max_length=64,
        label=ugettext_lazy('Are you a spammer?'),
        help_text=ugettext_lazy('Enter "no" if you are not a spammer.'),
    )

    def __init__(self, *args, **kwargs):
        super(ScriptFormUpdate, self).__init__(*args, **kwargs)
        self.label_suffix = ''
        self.fields['script'].choices = get_script_choices()


@disable_for_loaddata
def handler_script_saved(sender, **kwargs):
    try:
        script = kwargs['instance']
        script.md5sum = script.checksum(hashlib.md5)
        script.sha512sum = script.checksum(hashlib.sha512)
    except:  # noqa: E722
        pass


@disable_for_loaddata
def handler_scripts_changed(sender, **kwargs):
    """Build files scripts.{xml,json}(.gz) after update/delete of a script."""
    xml = '<?xml version="1.0" encoding="utf-8"?>\n'
    xml += '<plugins>\n'
    json_data = []
    strings = []

    # add disabled reasons in strings to translate
    reasons = set([script.disabled
                   for script in Script.objects.exclude(disabled='')])
    for reason in reasons:
        strings.append((reason, 'reason for a disabled script'))

    # build xml/json content
    script_list = Script.objects.filter(approved=True).order_by('id')
    for script in script_list:
        strings.append(
            (
                script.desc_en,
                'description for script "%s" (%s)' % (
                    script.name_with_extension(),
                    script.version_weechat()),
            )
        )
        if script.disabled:
            continue
        xml += '  <plugin id="%s">\n' % script.id
        json_script = OrderedDict([
            ('id', '%s' % script.id),
        ])
        for key, value in script.__dict__.items():
            value_i18n = {}
            if key in ('_state', 'id', 'approved', 'approval'):
                continue
            if value is None:
                value = ''
            else:
                if key == 'url':
                    # FIXME: use the "Host" from request, but…
                    # request is not available in this handler!
                    value = ('https://weechat.org/%s' %
                             script.build_url()[1:])
                elif key == 'mail':
                    value = value.replace('@', ' [at] ')
                    value = value.replace('.', ' [dot] ')
                elif key == 'md5sum':
                    value = script.get_md5sum()
                elif key == 'sha512sum':
                    value = script.get_sha512sum()
                elif key == 'desc_en':
                    for lang, locale in settings.LANGUAGES_LOCALES.items():
                        if lang[0:2] != 'en':
                            translation.activate(lang)
                            value_i18n['desc_%s' % locale] = ugettext(value)
                            translation.deactivate()
            value = '%s' % value
            xml += '    <%s>%s</%s>\n' % (key, escape(value), key)
            json_script[key] = value
            for field in value_i18n:
                xml += '    <%s>%s</%s>\n' % (field,
                                              escape(value_i18n[field]),
                                              field)
                json_script[field] = value_i18n[field]
        xml += '  </plugin>\n'
        json_data.append(json_script)
    xml += '</plugins>\n'

    # create scripts.xml
    filename = files_path_join('scripts.xml')
    with open(filename, 'w', encoding='utf-8') as _file:
        _file.write(xml)

    # create scripts.xml.gz
    with open(filename, 'rb') as _f_in:
        _f_out = gzip.open(filename + '.gz', 'wb')
        _f_out.writelines(_f_in)
        _f_out.close()

    # create scripts.json
    filename = files_path_join('scripts.json')
    with open(filename, 'w', encoding='utf-8') as _file:
        _file.write(json.dumps(json_data, indent=2, ensure_ascii=False,
                               separators=(',', ': ')))
        # json.dump(json_data, _file)

    # create scripts.json.gz
    with open(filename, 'rb') as _f_in:
        _f_out = gzip.open(filename + '.gz', 'wb')
        _f_out.writelines(_f_in)
        _f_out.close()

    # create _i18n_scripts.py
    i18n_autogen('scripts', 'scripts', strings)


pre_save.connect(handler_script_saved, sender=Script)
post_save.connect(handler_scripts_changed, sender=Script)
post_delete.connect(handler_scripts_changed, sender=Script)
