"""Offline, profile-driven emulation. Never imports or calls python-dbus.

Provides deterministic profile controls and prints intended FFADO calls to
stdout; it does NOT pretend to predict audio hardware registers or meter data.
"""
from pathlib import Path
import re
import contextlib
import math
import xml.etree.ElementTree as ET
from .profiles.loader import _common
from .profiles.resolver import resolve_mixer
from .profiles.capabilities import parse_capabilities, activate_internal_model, enabled

BASE='/org/ffado/Control/DeviceManager/'
# FFADO source: support/mixer-qt4/ffado/mixer, src/dice/*, src/motu.
# These are fixtures for UI testing, not live capabilities.
MIXER_FIXTURES={
 'profire2626':('profire2626','profire_2626_000d6c_00000010.xml',18,16),
 'profire610':('profire2626','profire_610_000d6c_00000011.xml',18,16),
 'saffirepro26':('saffire_dice','saffire_pro_26_00130e_00000012.xml',18,16),
 'motuultralite':('motu','motu_ultralite.xml',4,20),
}


def _catalog():
    """Generate debug identifiers from source-derived, explicit model profiles."""
    root=Path(__file__).parent/'profiles'
    catalog=dict(MIXER_FIXTURES)
    for common in sorted(root.glob('*/common.xml')):
        profile=_common(common)
        if not profile.get('mixer_matrix'): continue
        for path in sorted(common.parent.glob('*.xml')):
            if path.name in ('common.xml','reference.xml'): continue
            node=ET.parse(path).getroot()
            if node.tag != 'device' or node.get('extends')!='common.xml':continue
            # No mock for an identity-only/source-only profile.
            caps = parse_capabilities(node) if node.find('capabilities') is not None else {}
            if caps.get('status') != 'mapped' or caps['features']['matrix_gain']['state'] != 'mapped':
                continue
            alias=re.sub(r'[^a-z0-9]','',(node.get('name') or path.stem).lower())
            if alias not in catalog:
                catalog[alias]=(common.parent.name,path.name,18,16)
    return catalog


def fixture_names():
    """Return all model profiles with a declared and mockable mixer matrix."""
    return sorted(_catalog())


def _normalized_name(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def resolve_debug_profile(value):
    """Accept model name, XML filename or canonical debug name, case-insensitively.

    Do not guess a model for an unknown alias. Models without a mapped mixer
    matrix cannot currently be rendered as functional mock mixers.
    """
    catalog = _catalog()
    lookup = {}
    ambiguous = set()
    for alias, (family, filename, _rows, _cols) in catalog.items():
        profile_path = Path(__file__).parent / 'profiles' / family / filename
        display_name = ET.parse(profile_path).getroot().get('name') or ''
        for candidate in (alias, Path(filename).stem, filename, display_name):
            key = _normalized_name(candidate)
            if key in lookup and lookup[key] != alias:
                ambiguous.add(key)
            else:
                lookup[key] = alias
    key = _normalized_name(value)
    if key in ambiguous:
        raise ValueError(f'Ambiguous debug profile {value!r}. Use one of: {", ".join(fixture_names())}')
    if key not in lookup:
        raise ValueError(f'Unknown or unsupported debug profile {value!r}. '
                         f'Use --debug list to see the {len(catalog)} profiles with a mapped mixer matrix.')
    return lookup[key]


def create_fixture(alias):
    alias = resolve_debug_profile(alias)
    catalog=_catalog()
    if alias not in catalog:
        raise ValueError(f'Unknown debug profile {alias!r}. Choices: {", ".join(fixture_names())}')
    family,filename,a,b=catalog[alias]
    p=Path(__file__).parent/'profiles'/family
    profile=_common(p/'common.xml')
    profile['device_profile']=filename
    node=ET.parse(p/filename).getroot()
    profile['device_name']=node.get('name')
    if node.get('model_id'):
        profile = activate_internal_model({**profile, 'capabilities':{'status':'requires_internal_model'}}, int(node.get('model_id'), 0))
    else:
        profile['capabilities']=parse_capabilities(node)
    if not enabled(profile, 'matrix_gain'):
        raise ValueError(f'No mapped mixer controls in {filename}')
    # Synthetic dimensions are explicitly debug-only; real device dimensions
    # always come from the named MatrixMixer interface at runtime.
    match=node.find('match')
    internal_id = int(node.get('model_id','0'), 0)
    if match is not None:
        vendor=int(match.get('vendor_id'),0)
        config_model=int(match.get('configuration_model_id'),0)
    elif family=='motu':
        vendor, config_model=0x1f2, 0
    else:
        raise ValueError(f'Debug fixture lacks exact FFADO identity: {filename}')
    # Synthetic, deterministic GUID (not a real serial). Distinct across the
    # same FFADO generation's internal model variants; no physical device use.
    path=BASE+f'{vendor:06x}{config_model:08x}{internal_id:02x}'
    hint=profile['mixer_matrix']; mat_path=hint['path']
    r,c=(4,20) if family=='motu' else (a,b)
    if hint.get('row_role')=='inputs':
        row_names=[f'Mixer/In:{i+1:02d}\n(Anlg/In:{i+1:02d})' for i in range(r)]
        col_names=[f'Mixer/Out:{i+1:02d}' for i in range(c)]
    else:
        row_names=[f'Mix {i+1}' for i in range(r)]
        # MOTU source: src/motu/motu_mixerdefs.cpp (8 analog, 2 AES,
        # 2 S/PDIF, 8 ADAT columns; model XML hides unavailable ones).
        col_names=([f'Analog {i}' for i in range(1,9)] +
                   [f'AES/EBU {i}' for i in range(1,3)] +
                   [f'SPDIF {i}' for i in range(1,3)] +
                   [f'ADAT {i}' for i in range(1,9)]) if family=='motu' else [f'Input {i+1}' for i in range(c)]
    matrix={'path':path+mat_path,'name':mat_path.rsplit('/',1)[-1],
            'rows':r,'cols':c,'row_names':row_names,'col_names':col_names}
    controls=[]
    if family=='motu':
        for i in range(1,5):
            controls.extend([{'path':path+f'/Mixer/Mix{i}/Mix_{suffix}', 'kind':'Discrete', 'label':f'Mix {i} {suffix}'}
                for suffix in ('fader','dest')])
        controls.extend([{'path':path+'/Mixer/Info/Model','kind':'Discrete', 'label':'Model'},
                         {'path':path+'/Mixer/Info/SampleRate','kind':'Discrete','label':'SampleRate'}])
    device={'guid':path.split('/')[-1], 'device':path, 'vendor_id':vendor,
            'model_id':config_model, 'unit_version':(0x14 if family=='motu' else config_model if family=='rme' else None),
            'controls':controls,'matrices':[matrix],
            'routers':[] if family in ('motu','motu_mark3','rme') else [{'path':path+'/EAP/Router'}]}
    return device,profile


class TraceHelper:
    """In-memory D-Bus double which cannot create a session bus."""
    def __init__(self, device):
        self.device=device
        self.cells={}
        self.values={device['device']+'/Mixer/Info/Model':int(device['guid'][-2:],16),
                     device['device']+'/Mixer/Info/SampleRate':48000}
        self.routing={'Line/Out:01':'Mixer/Out:01'}
    @contextlib.contextmanager
    def transaction(self): yield
    def _trace(self, path, kind, method, *args):
        print('[DEBUG would call D-Bus]',path,kind+'.'+method,repr(args),flush=True)
    def get_cell(self,path,row,col):
        self._trace(path,'MatrixMixer','getValue',row,col)
        return self.cells.get((path,row,col),16384 if ('EAP/' in path or any(path.endswith('/Mixer/' + name) for name in ('InputFaders','PlaybackFaders','OutputFaders'))) else 100)
    def set_cell(self,path,row,col,value):
        self._trace(path,'MatrixMixer','setValue',row,col,value)
        self.cells[(path,row,col)]=value
    def get_value(self,path,kind):
        self._trace(path,kind,'getValue')
        return self.values.get(path,0)
    def set_value(self,path,kind,value):
        self._trace(path,kind,'setValue',value)
        self.values[path]=value
    def router_call(self,path,method,*args):
        self._trace(path,'CrossbarRouter',method,*args)
        if method=='getSourceNames':return ['Mixer/Out:01','Mute:00']
        if method=='getDestinationNames':return ['Line/Out:01']
        if method=='getSourceForDestination':return self.routing[args[0]]
        if method=='setConnectionState':
            self.routing[args[1]]=args[0] if args[2] else 'Mute:00'
            return True
        if method=='hasPeakMetering':return True
        if method=='getPeakValues':
            # Synthetic 12-bit DICE readings for *offline* meter display.
            # These do not represent actual hardware peaks and send no D-Bus.
            return [('Mixer/In:01',0),('Mixer/In:02',1024),
                    ('Mixer/In:03',2048),('Mixer/In:04',4095),
                    ('Line/Out:01',768)]
        raise ValueError(method)


def make_debug_mixer(alias, config):
    from .mixer import Mixer
    d,profile=create_fixture(alias)
    # skip FFADO discovery and package lookup; pin the explicit test profile.
    class DebugMixer(Mixer):
        def _find_profile(self): return profile
    return DebugMixer(config,device=d,helper=TraceHelper(d))
