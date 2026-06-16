import chromadb
from pathlib import Path
from openai import OpenAI
client=chromadb.PersistentClient(path="")
collection=client.get_or_create_collection("knowledge")
def add_chunk(id,text,embedding,metadatas):
    collection.add(ids=[id],documents=[text],embeddings=[embedding],metadatas=[metadatas])

def search(query_embedding,n=5):
    return collection.query(query_embeddings=[query_embeddings],n_results=n)

def ingest_direstory(path=""):
    for md_file in Path(path).rglob("*.md"):
        text=md_file.read_text(encoding="utf-8")
        chunks=split_text(text,chunk_size=512)
        for i,chunk in enumerate(chunks):
            embedding=embed(chunks)
            add_chunk(f"{md_file.stem}_{i}",chunks,embedding,{"source":str(md_file)})

client=OpenAI(api_key="")
def generate_answer(query,context):
    prompt=f""
    response=client.chat.completions.create(
        model="",
        messages=[{"role":"user","content":prompt}]
    )
    return response.choices[0].message.content

