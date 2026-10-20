#!/usr/bin/env python3 -I
"""Convert a saved HTML file to plain-ish markdown: headings, paragraphs, lists, tables, links."""
import sys, re, html
from html.parser import HTMLParser

class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out=[]; self.links=[]; self.skip=0; self.href=None; self.cell=False; self.row=[]
        self.in_table=False; self.buf=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in('script','style','noscript','svg'): self.skip+=1; return
        if tag in('h1','h2','h3','h4','h5','h6'): self.out.append('\n\n'+'#'*int(tag[1])+' ')
        elif tag in('p','div','section','article','li','br','tr','figcaption','blockquote'):
            if tag=='li': self.out.append('\n- ')
            elif tag=='tr': self.out.append('\n| ')
            else: self.out.append('\n')
        elif tag in('td','th'): self.out.append(' ')
        elif tag=='a' and a.get('href'):
            self.href=a['href']; self.links.append(a['href']); self.out.append('[')
        elif tag=='img' and a.get('alt'): self.out.append('['+a['alt']+']')
    def handle_endtag(self,tag):
        if tag in('script','style','noscript','svg'): self.skip-=1; return
        if tag in('td','th'): self.out.append(' |')
        elif tag=='a' and self.href is not None: self.out.append(']('+self.href+')'); self.href=None
        elif tag in('h1','h2','h3','h4','h5','h6','p','li','tr'): self.out.append('\n')
    def handle_data(self,d):
        if self.skip: return
        d=re.sub(r'\s+',' ',d)
        if d.strip(): self.out.append(d)
p=P(); p.feed(open(sys.argv[1],encoding='utf-8',errors='replace').read())
txt=''.join(p.out); txt=re.sub(r'\n[ \t]+','\n',txt); txt=re.sub(r'\n{3,}','\n\n',txt)
print(txt)
print('\n\n## LINKS FOUND\n')
seen=set()
for l in p.links:
    if l not in seen: seen.add(l); print('- '+l)
