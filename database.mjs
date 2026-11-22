import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { issues } from './public/data.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const dataDir = process.env.RAG_LIBRARY_DIR || path.join(root, 'database');
export const uploadsDir = path.join(dataDir, 'uploads');
fs.mkdirSync(uploadsDir, { recursive: true });

const require = createRequire(import.meta.url);
let Database;
try {
  Database = require('node:sqlite').DatabaseSync;
} catch {
  Database = require('better-sqlite3');
}
const db = new Database(path.join(dataDir, 'research.sqlite'));
db.exec('PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;');

function transaction(write) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const result = write();
    db.exec('COMMIT');
    return result;
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

db.exec(`
CREATE TABLE IF NOT EXISTS publications (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, authors TEXT, year INTEGER,
  kind TEXT, abstract TEXT, task TEXT, protocol TEXT, pages INTEGER,
  file_name TEXT, pending INTEGER NOT NULL DEFAULT 1, demo INTEGER NOT NULL DEFAULT 0,
  config_json TEXT NOT NULL DEFAULT '{}', datasets_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '{}', full_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rag_configs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL UNIQUE REFERENCES publications(id) ON DELETE CASCADE,
  variant TEXT, top_k REAL, chunk_size REAL, chunk_overlap REAL, embedding TEXT, model TEXT, retrieval TEXT,
  config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  name TEXT NOT NULL, task TEXT, protocol TEXT
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  experiment_key TEXT, config_id TEXT, task TEXT, dataset TEXT, protocol TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
  id TEXT NOT NULL, publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  experiment_id TEXT, config_id TEXT, task TEXT, dataset TEXT, protocol TEXT, name TEXT NOT NULL,
  raw TEXT, unit TEXT, value REAL, page INTEGER, fragment TEXT, origin TEXT, metric_json TEXT NOT NULL, PRIMARY KEY(publication_id,id)
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  field TEXT NOT NULL, page INTEGER, fragment TEXT
);
CREATE TABLE IF NOT EXISTS validation_issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT, publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pdf_files (
  publication_id TEXT PRIMARY KEY REFERENCES publications(id) ON DELETE CASCADE,
  stored_name TEXT NOT NULL, original_name TEXT NOT NULL, size_bytes INTEGER, mime_type TEXT DEFAULT 'application/pdf'
);
CREATE TABLE IF NOT EXISTS collections (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS collection_publications (
  collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  PRIMARY KEY(collection_id, publication_id)
);
`);

const insertPublication = db.prepare(`INSERT INTO publications
(id,title,authors,year,kind,abstract,task,protocol,pages,file_name,pending,demo,config_json,datasets_json,evidence_json,full_json,updated_at)
VALUES (@id,@title,@authors,@year,@kind,@abstract,@task,@protocol,@pages,@file_name,@pending,@demo,@config_json,@datasets_json,@evidence_json,@full_json,CURRENT_TIMESTAMP)
ON CONFLICT(id) DO UPDATE SET title=excluded.title,authors=excluded.authors,year=excluded.year,kind=excluded.kind,
abstract=excluded.abstract,task=excluded.task,protocol=excluded.protocol,pages=excluded.pages,file_name=excluded.file_name,
pending=excluded.pending,demo=excluded.demo,config_json=excluded.config_json,datasets_json=excluded.datasets_json,
evidence_json=excluded.evidence_json,full_json=excluded.full_json,updated_at=CURRENT_TIMESTAMP`);
const insertMetric = db.prepare(`INSERT INTO metrics
(id,publication_id,experiment_id,config_id,task,dataset,protocol,name,raw,unit,value,page,fragment,origin,metric_json)
VALUES (@id,@publication_id,@experiment_id,@config_id,@task,@dataset,@protocol,@name,@raw,@unit,@value,@page,@fragment,@origin,@metric_json)`);
const insertDataset = db.prepare('INSERT INTO datasets(publication_id,name,task,protocol) VALUES (?,?,?,?)');
const insertExperiment = db.prepare('INSERT INTO experiments(publication_id,experiment_key,config_id,task,dataset,protocol) VALUES (?,?,?,?,?,?)');
const insertSource = db.prepare('INSERT INTO sources(publication_id,field,page,fragment) VALUES (?,?,?,?)');

function writePaper(p) {
  if (!p || typeof p.id !== 'string' || !p.id || typeof p.title !== 'string') throw new Error('Некорректная карточка публикации.');
    insertPublication.run({
      id:p.id,title:p.title,authors:p.authors||'',year:Number(p.year)||null,kind:p.kind||'PDF',abstract:p.abstract||'',
      task:p.task||'',protocol:p.protocol||'',pages:Number(p.pages)||null,file_name:p.file||'',
      pending:p.pending?1:0,demo:p.demo?1:0,config_json:JSON.stringify(p.config||{}),
      datasets_json:JSON.stringify(p.datasets||[]),evidence_json:JSON.stringify(p.evidence||{}),full_json:JSON.stringify(p)
    });
    db.prepare('DELETE FROM rag_configs WHERE publication_id=?').run(p.id);
    db.prepare('DELETE FROM datasets WHERE publication_id=?').run(p.id);
    db.prepare('DELETE FROM experiments WHERE publication_id=?').run(p.id);
    db.prepare('DELETE FROM metrics WHERE publication_id=?').run(p.id);
    db.prepare('DELETE FROM sources WHERE publication_id=?').run(p.id);
    db.prepare('DELETE FROM validation_issues WHERE publication_id=?').run(p.id);
    const c=p.config||{};
    db.prepare(`INSERT INTO rag_configs(publication_id,variant,top_k,chunk_size,chunk_overlap,embedding,model,retrieval,config_json)
      VALUES (?,?,?,?,?,?,?,?,?)`).run(p.id,c.variant??null,Number(c.top_k)||null,Number(c.chunk_size)||null,
      c.chunk_overlap == null ? null : Number(c.chunk_overlap),c.embedding??null,c.model??null,c.retrieval??null,JSON.stringify(c));
    for (const d of p.datasets||[]) if (typeof d==='string') insertDataset.run(p.id,d,p.task||'',p.protocol||'');
    const seen=new Set();
    for (const m of p.metrics||[]) {
      const key=JSON.stringify([m.experiment_id,m.config_id,m.task,m.dataset,m.protocol]);
      if (!seen.has(key)) { seen.add(key); insertExperiment.run(p.id,m.experiment_id||'',m.config_id||'',m.task||'',m.dataset||'',m.protocol||''); }
      insertMetric.run({id:String(m.id||`${p.id}-metric-${Math.random()}`),publication_id:p.id,
        experiment_id:m.experiment_id||'',config_id:m.config_id||'',task:m.task||'',dataset:m.dataset||'',
        protocol:m.protocol||'',name:m.name||'Без названия',raw:m.raw??'',unit:m.unit||'',value:m.value != null && Number.isFinite(Number(m.value))?Number(m.value):null,
        page:Number(m.page)||null,fragment:m.fragment||'',origin:m.origin||'',metric_json:JSON.stringify(m)});
    }
    for (const [field,e] of Object.entries(p.evidence||{})) if (e) insertSource.run(p.id,field,Number(e.page)||null,e.fragment||'');
    const addIssue = db.prepare('INSERT INTO validation_issues(publication_id,message) VALUES (?,?)');
    for (const message of issues(p)) addIssue.run(p.id,message);
}
export function updatePaper(p) {
  transaction(() => {
    const existing = db.prepare('SELECT file_name FROM publications WHERE id=? AND demo=0').get(p.id);
    if (!existing) throw Error('Публикация не найдена.');
    writePaper({...p, file:existing.file_name, demo:false});
  });
}
export function getPapers() {
  return db.prepare('SELECT full_json FROM publications ORDER BY demo, created_at DESC, rowid').all().map(r=>JSON.parse(r.full_json));
}
export function saveCollection(c) {
  if (!c || typeof c.id!=='string' || typeof c.name!=='string') throw new Error('Некорректная коллекция.');
  transaction(()=>{
    db.prepare('INSERT INTO collections(id,name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name').run(c.id,c.name);
    db.prepare('DELETE FROM collection_publications WHERE collection_id=?').run(c.id);
    const add=db.prepare('INSERT OR IGNORE INTO collection_publications(collection_id,publication_id) VALUES (?,?)');
    for(const id of c.ids||[]) add.run(c.id,id);
  });
}
export function getCollections() {
  return db.prepare(`SELECT c.id,c.name,COALESCE(json_group_array(cp.publication_id) FILTER (WHERE cp.publication_id IS NOT NULL),'[]') AS ids
    FROM collections c LEFT JOIN collection_publications cp ON cp.collection_id=c.id GROUP BY c.id ORDER BY c.created_at`).all()
    .map(c=>({...c,ids:JSON.parse(c.ids)}));
}
export function createPaper(paper, buffer) {
  const storedName = randomUUID() + '.pdf';
  const file = path.join(uploadsDir,storedName);
  fs.writeFileSync(file,buffer,{flag:'wx'});
  try {
    transaction(() => {
      if (db.prepare('SELECT 1 FROM publications WHERE id=?').get(paper.id)) throw Error('Публикация уже существует.');
      writePaper(paper);
      db.prepare('INSERT INTO pdf_files(publication_id,stored_name,original_name,size_bytes) VALUES (?,?,?,?)')
        .run(paper.id,storedName,paper.file,buffer.length);
    });
  } catch (error) {
    fs.unlinkSync(file);
    throw error;
  }
}
export function getPdf(id) {
  const row=db.prepare('SELECT stored_name,original_name FROM pdf_files WHERE publication_id=?').get(id);
  if(!row) return null;
  const file=path.join(uploadsDir,row.stored_name);
  return fs.existsSync(file)?{file, name:row.original_name}:null;
}

const examples = JSON.parse(fs.readFileSync(new URL('./public/examples/library.json',import.meta.url),'utf8'));
transaction(() => {
  const exists = db.prepare('SELECT 1 FROM publications WHERE id=?');
  for (const example of examples) {
    if (!exists.get(example.id)) writePaper(example);
  }
});
if (!db.prepare('SELECT 1 FROM collections WHERE id=?').get('benchmarks')) {
  saveCollection({id:'benchmarks', name:'RAG-бенчмарки', ids:['demo-1','demo-2','demo-4']});
}
