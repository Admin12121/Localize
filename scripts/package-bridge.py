"""Build companion ZIP and single-file launcher from the same package payload."""
from release_inputs import ROOT,OUT,clean_bytes,companion_payload,write_zip

payload=companion_payload()
write_zip(OUT/'web-bridge-companion.zip',payload,'web-bridge-companion/')
write_zip(OUT/'Web-Bridge.pyz',{'__main__.py':clean_bytes(ROOT/'scripts/bundle-entry.py'),**{'app/'+name:data for name,data in payload.items()}})
print('Packaged companion ZIP and single-file launcher from the canonical package.')
