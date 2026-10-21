import sys
from pypdf import PdfReader
r=PdfReader(sys.argv[1])
for i,p in enumerate(r.pages):
    for a in p.get('/Annots') or []:
        o=a.get_object()
        u=o.get('/A',{}).get('/URI') if o.get('/A') else None
        if u: print(i+1, u)
