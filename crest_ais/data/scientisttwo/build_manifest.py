import json, pathlib, re, hashlib, datetime
root=pathlib.Path(__file__).parent
rows=json.loads((root/'download_results.json').read_text())
titles={r['file']:r for r in json.loads((root/'extracted_titles.json').read_text())}
tree=json.loads((root/'repository_tree.json').read_text())
blobs={x['path']:x for x in tree['tree']}
# Resolve typesetting line-break hyphenation in extracted first-page titles.
rep={
'STRUC-TURE':'STRUCTURE','RE-CURRENT':'RECURRENT','POPULA-TION':'POPULATION',
'TOKENIZA-TION':'TOKENIZATION','IMPU-TATION':'IMPUTATION','GEOM-ETRY':'GEOMETRY',
'DISCREP-ANCY':'DISCREPANCY','RANDOM-IZED':'RANDOMIZED','FEA-SIBILITY':'FEASIBILITY',
'CON-TACT':'CONTACT','MONGE-AMP`ERE':'MONGE-AMPÈRE','AT-TENTION':'ATTENTION',
'FIL-TERING':'FILTERING','TABU-LAR':'TABULAR','DIF-FUSION':'DIFFUSION',
'LEGEN-DRE':'LEGENDRE','PRE-VENTING':'PREVENTING','IN-FERENCE':'INFERENCE',
'SPEC-TRAL':'SPECTRAL','COM-PANDING':'COMPANDING','Op-timization':'Optimization',
'GENERA-TION':'GENERATION','REG-ULARIZATION':'REGULARIZATION','SE-LECTION':'SELECTION',
'HO-EFFDING':'HOEFFDING','CURVA-TURE':'CURVATURE','DECOMPOSI-TIONS':'DECOMPOSITIONS',
'DISTRIBUTION-ALLY':'DISTRIBUTIONALLY','R´ENYI':'RÉNYI','MATCH-ING':'MATCHING',
'NYSTR ¨OM':'NYSTRÖM','SUB-SPACE':'SUBSPACE','SUR-VIVAL':'SURVIVAL',
'HYPOEL-LIPTIC':'HYPOELLIPTIC','VEHI-CLE':'VEHICLE','SEGMENTA-TION':'SEGMENTATION',
'ASSESS-MENT':'ASSESSMENT','CIR-CUIT':'CIRCUIT','TRAJECTO-RIES':'TRAJECTORIES',
'OPERA-TOR':'OPERATOR','AUTOEN-CODERS':'AUTOENCODERS','CONFOR-MAL':'CONFORMAL',
'NOS´E':'NOSÉ','CON-VERGENCE':'CONVERGENCE','VERIFI-CATION':'VERIFICATION'
}
papers=[]
for idx,row in enumerate(rows,1):
 if 'error' in row: continue
 rel=row['file'].removeprefix('generated-papers/')
 title=titles[rel]['title']
 for a,b in rep.items(): title=title.replace(a,b)
 label=row['label']; subdomain=label.split(' (',1)[0]
 category=pathlib.PurePosixPath(rel).parts[0]
 page_url='https://scientist-two.github.io/#'+category+'/'+__import__('urllib.parse',fromlist=['quote']).quote(label,safe='')
 papers.append({
  'id':'scientisttwo_'+re.sub(r'[^a-z0-9]+','_',rel.removesuffix('.pdf').lower()).strip('_'),
  'title':title,'source_url':page_url,'pdf_url':row['pdf_url'],
  'pdf_path':'data/scientisttwo/papers/'+rel,'sha256':row['sha256'],
  'published_date':None,'topic':category.replace('_',' ')+' / '+subdomain,
  'provenance':'Official generated-paper gallery in the project website linked by author-submitted arXiv:2609.19644. Downloaded PDF bytes match Git blob '+blobs[row['file']]['sha']+' in scientist-two/scientist-two.github.io at commit '+tree['sha']+'.',
  'license':'Apache-2.0','gallery_label':label,
  'title_source':'PDF first page; normalized line breaks, discretionary word hyphens and decomposed accents.',
  'byte_length':row['bytes'],'page_count':titles[rel]['pages'],
  'repository_path':row['file'],'repository_blob_sha1':blobs[row['file']]['sha']
 })
manifest={
 'agent_id':'scientisttwo','display_name':'ScientistTwo (Google Cloud AI Research)',
 'official_source_urls':['https://arxiv.org/abs/2609.19644','https://scientist-two.github.io/','https://github.com/scientist-two/scientist-two.github.io'],
 'identity_confidence':'high: author-submitted system preprint directly links the project website; same title and author list; official project gallery explicitly identifies these as autonomously generated papers.',
 'selection_notes':[
  'All 86 generated-paper PDFs linked in the live official project gallery, across all eight project categories, were downloaded. Their exact bytes match the official GitHub repository at the recorded commit. No duplicate SHA256 hashes.',
  'The 107 benchmark problems are not 107 released generated papers. The official release contains 86 generated manuscripts; the collection is exhaustive for that gallery and current generated-papers repository tree, not every historical experiment.',
  'Excluded the human-authored system-description preprint arXiv:2609.19644 and static/figures/overview.pdf and static/figures/teaser.pdf (figure assets rather than generated manuscripts).',
  'published_date is null because individual generated-paper release/publication dates are not declared in gallery. PDF metadata creation dates and template conference headers are not verified publication dates.',
  'Many generated PDFs retain template conference/under-review headers and generic or anonymous author fields. These do not establish actual ICLR acceptance. Scientific results and system provenance claims are author-reported.',
  'Apache-2.0 is the official repository-root license, preserved as LICENSE.txt; no separate per-PDF license notice was identified. This is repository provenance, not an independent legal opinion.',
  'Titles come from actual PDF first pages rather than abbreviated gallery labels; normalization removes typesetting word breaks while retaining substantive method hyphens.'
 ],
 'retrieved_date':'2026-10-26','repository_commit':tree['sha'],
 'papers':papers,'unavailable_candidates':[],
 'excluded_assets':[
  {'source_url':'https://arxiv.org/abs/2609.19644','reason':'Human-authored system-description paper; not a generated output.'},
  {'source_url':'https://scientist-two.github.io/static/figures/overview.pdf','reason':'System overview figure asset.'},
  {'source_url':'https://scientist-two.github.io/static/figures/teaser.pdf','reason':'Teaser figure asset.'}
 ]
}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
notes='''ScientistTwo corpus research notes
Retrieved: 2026-10-26

Identity and primary sources:
ScientistTwo is the autonomous scientific research system of Jaehyun Nam, Jinsung Yoon, Yanzhou Pan, Yubo Wang, Rui Meng, Parthasarathy Ranganathan and Tomas Pfister, Google Cloud AI Research.
The author-submitted description is arXiv:2609.19644, submitted September 17, 2026:
https://arxiv.org/abs/2609.19644
Its abstract directly links the project website:
https://scientist-two.github.io/
The website source and output PDFs are in:
https://github.com/scientist-two/scientist-two.github.io
The unrelated smirnovlad/GoogleScientistTwo repository calls itself a replication and was not selected.

Collection:
The official page's embedded paperData gallery contains 86 entries in eight categories. The current GitHub recursive tree contains the identical 86 generated-papers PDFs. The only additional PDFs are overview/teaser figure assets; no additional generated manuscript candidates were found. Downloaded all 86 manuscripts as exact bytes from the live official website. Each file starts with a PDF signature, opens with PyMuPDF and matches the corresponding Git blob SHA1. SHA256, page count and exact byte length are recorded per paper. No SHA256 duplicates. Total PDF bytes: 235533685.

Counts by project category: Applications 15; Deep Learning 24; General ML 14; Optimization 5; Probabilistic 10; RL 3; Social Aspects 9; Theory 6.

Exclusions and caveats:
The description preprint, website figure assets, and other systems' papers are excluded. The 107 research tasks discussed by authors are benchmark inputs; only the 86 released generated outputs are included.
Individual publication dates are unavailable. Do not substitute PDF creation metadata or preprint date. Some PDF templates claim conference publication or under-review status for ICLR 2025; these strings do not establish actual venue acceptance. Anonymous/generic author fields remain in source PDFs. The collection records authors' explicit generated-output provenance, without independently validating scientific claims or autonomy.
The repository has an Apache-2.0 root license saved as LICENSE.txt. No distinct per-PDF licenses were identified. Titles were read from PDF first-page text; line wrapping, discretionary hyphenation and detached accents were normalized in manifest titles.

Reproducibility artifacts:
project_page.html: exact downloaded official gallery HTML.
repository_tree.json: GitHub recursive tree response, including recorded commit.
gallery_entries.json: parsed official gallery list.
download_results.json: download URLs, byte lengths and SHA256.
extracted_titles.json: first-page title lines before normalization.
manifest.json: evaluation corpus manifest.
No repository scripts were executed, no paid calls made, and no secrets or environment files accessed.
'''
(root/'notes.txt').write_text(notes)
print('Manifest written:',len(papers),'papers at',root/'manifest.json')
