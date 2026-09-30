"""Run with python3 test_office_dogs.py: verify the shipped dog assets."""
import json
import struct
from pathlib import Path


def check():
    root = Path(__file__).parent / 'assets' / 'dogs'
    for agent in ('marcus', 'dyson', 'solomon', 'midas'):
        folder = root / agent
        manifest = json.loads((folder / 'manifest.json').read_text())
        assert manifest['agentId'] == agent and manifest['anatomy'] == 'quadruped'
        assert Path(manifest['model']).name == manifest['model']
        for field in ('model', 'reference', 'preview'):
            assert (folder / manifest[field]).is_file(), (agent, field)
        data = (folder / manifest['model']).read_bytes()
        magic, version, length = struct.unpack_from('<4sII', data)
        assert magic == b'glTF' and version == 2 and length == len(data), agent
        chunk_length, chunk_type = struct.unpack_from('<I4s', data, 12)
        assert chunk_type == b'JSON'
        model = json.loads(data[20:20 + chunk_length])
        assert model.get('meshes') and model.get('materials') and model.get('textures'), agent
        triangles = 0
        for mesh in model['meshes']:
            for primitive in mesh['primitives']:
                assert primitive.get('mode', 4) == 4
                count = model['accessors'][primitive['indices']]['count']
                assert count > 0 and count % 3 == 0
                triangles += count // 3
        assert triangles == manifest['triangles'] and triangles <= 30000, agent
        if manifest['animation'] == 'quadruped-walk':
            assert model.get('skins') and model.get('animations'), agent
        print(agent, triangles, 'triangles:', manifest['animation'])


if __name__ == '__main__':
    check()
