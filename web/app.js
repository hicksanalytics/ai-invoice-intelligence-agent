let documents=[], selected=null;
const $=id=>document.getElementById(id);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed.');return d;}
function state(r){if(r.review_status==='approved')return ['Approved','good'];if(r.review_status==='rejected')return ['Rejected','error'];if(r.validation_status==='failed')return ['Extraction failed','error'];if(r.validation_status==='needs_correction')return ['Needs correction','warn'];return ['Ready for review',''];}
async function refresh(){documents=await api('/api/documents');render();if(selected)show(selected);}
function render(){
 const counts=[['Documents',documents.length],['Needs attention',documents.filter(r=>r.review_status==='pending'&&r.validation_status!=='ready').length],['Ready for review',documents.filter(r=>r.review_status==='pending'&&r.validation_status==='ready').length],['Approved',documents.filter(r=>r.review_status==='approved').length]];
 $('stats').replaceChildren(...counts.map(([label,count])=>{const n=node('div',undefined,'stat');n.append(node('strong',count),node('span',label));return n;}));
 const filter=$('filter').value;const list=documents.filter(r=>filter==='all'||(filter==='attention'?r.review_status==='pending'&&r.validation_status!=='ready':filter==='ready'?r.review_status==='pending'&&r.validation_status==='ready':r.review_status===filter));
 $('queue').replaceChildren(...list.map(r=>{const b=node('button',undefined,'invoice-card'+(selected===r.id?' selected':''));const inv=r.invoice;b.append(node('strong',inv?.vendor||r.filename),node('div',`#${r.id} · ${inv?.invoice_number||'Number missing'} · ${inv?.currency||''} ${inv?.total||'—'}`,'meta'));const [label,cls]=state(r);b.append(node('span',label,'badge '+cls));b.onclick=()=>{selected=r.id;render();show(r.id);};return b;}));
 if(!list.length)$('queue').append(node('p','No documents in this view. Load the samples with python app.py demo or add an invoice.'));
}
async function show(id){const r=documents.find(x=>x.id===id);if(!r)return;const pane=$('detail');pane.replaceChildren(node('p',r.filename,'eyebrow'),node('h2',r.invoice?.vendor||'Extraction review'));
 const [label,cls]=state(r);pane.append(node('span',label,'badge '+cls),node('p',`${r.mode==='demo'?'Deterministic demo parser':`Ollama · ${r.model}`} · ${r.created_at}`,'meta'));
 if(r.invoice){const grid=node('div',undefined,'definition');for(const k of ['invoice_number','invoice_date','due_date','currency','subtotal','tax','total']){const cell=node('div');cell.append(node('small',k.replaceAll('_',' ')),node('strong',r.invoice[k]??'Missing'));grid.append(cell);}pane.append(grid);
 const t=node('table');const head=node('tr');for(const l of ['Item','Qty','Unit','Amount'])head.append(node('th',l));t.append(head);for(const line of r.invoice.line_items){const row=node('tr');for(const k of ['description','quantity','unit_price','amount'])row.append(node('td',line[k]??'Missing'));t.append(row);}pane.append(t);}
 if(r.findings.length){const f=node('div',undefined,'findings');f.append(node('strong',`${r.findings.length} finding(s)`));for(const x of r.findings)f.append(node('p',x.message));pane.append(f);}
 if(r.error)pane.append(node('p',r.error,'error-text'));
 if(!r.error&&!r.findings.length)pane.append(node('p','No deterministic rule findings. Check every extracted field against the original document before approving.'));
 const details=node('details');details.append(node('summary','Extracted JSON and source fingerprint'),node('pre',JSON.stringify({source_hash:r.source_hash,extraction:r.raw},null,2)));pane.append(details);
 if(r.review_status==='pending'){
 const actor=node('input');actor.placeholder='Reviewer name';const actorL=node('label','Reviewer');actorL.append(actor);const note=node('textarea');note.placeholder='What did you verify against the source?';const noteL=node('label','Verification note');noteL.append(note);pane.append(actorL,noteL);
 const feedback=node('p');feedback.setAttribute('role','status');const approve=node('button','Approve verified record');approve.disabled=r.validation_status!=='ready';const reject=node('button','Reject','secondary');
 for(const [b,action] of [[approve,'approved'],[reject,'rejected']])b.onclick=async()=>{try{await api('/api/review',{id:r.id,action,actor:actor.value,note:note.value});await refresh();}catch(e){feedback.textContent=e.message;}};
 pane.append(approve,reject,feedback);}
 const events=await api('/api/audit/'+id);if(selected!==id)return;const log=node('details');log.append(node('summary','Audit history'));for(const e of events)log.append(node('p',`${e.created_at} · ${e.action} · ${e.actor}: ${e.note}`,'meta'));pane.append(log);
}
$('filter').onchange=render;
$('upload').onsubmit=async e=>{e.preventDefault();const file=$('file').files[0];if(!file)return;const msg=$('upload-message');if(file.size>10*1024*1024){msg.textContent='File exceeds 10 MB.';return;}
 const amount=Number($('threshold').value);if(!Number.isFinite(amount)||amount<0){msg.textContent='Enter a nonnegative threshold.';return;}
 $('process').disabled=true;msg.textContent='Extracting and checking the document…';
 try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});const result=await api('/api/ingest',{filename:file.name,data,mode:$('mode').value,model:$('model').value,threshold_cents:Math.round(amount*100)});selected=result.id;msg.textContent=result.reused?'This exact document is already in the queue. Showing its existing record.':'Saved to the review queue. Inspect the result below.';await refresh();}catch(e){msg.textContent=e.message;}finally{$('process').disabled=false;}};
refresh().catch(e=>{$('detail').textContent=e.message;});
