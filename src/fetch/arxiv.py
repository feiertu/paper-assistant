import requests 
import xml.etree.ElementTree as ET
 
def fetch_arxiv_metadata(query,max_results=5):
    base_url= "http://export.arxiv.org/api/query"
    params={
        "search_query":query,
        "start":0,
        "max_results":max_results,
        "sortBy":"submittedDate",
        "sortOrder":"descending"
        
    }

    response=requests.get(base_url,params=params,timeout=20)
    
    if response.status_code !=200:
        print(f"API ERROr:{response.status_code}")
        return []
    
    return parse_xml(response.content)

def parse_xml(xml_content):
    root = ET.fromstring(xml_content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    papers = []
    
    for entry in root.findall('atom:entry', ns):
        id_url = entry.find('atom:id', ns).text
        arxiv_id = id_url.split('/')[-1]
        
        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        summary = entry.find('atom:summary', ns).text.strip()
        authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
        published = entry.find('atom:published', ns).text
        
        pdf_url = None
        for link in entry.findall('atom:link', ns):
            href = link.attrib.get('href', '')
            if (link.attrib.get('type') == 'application/pdf' or 
                href.endswith('.pdf') or 
                link.attrib.get('title') == 'pdf'):
                pdf_url = href
                break
        
        papers.append({
            'id': arxiv_id,
            'title': title,
            'authors': ", ".join(authors),
            'summary': summary,
            'published': published,
            'pdf_url': pdf_url
        })
    
    return papers
    
papers = fetch_arxiv_metadata("cat:cs.AI AND ti:learning", max_results=3)
for p in papers:
    print(f"标题: {p['title']}")
    print(f"作者: {p['authors']}")
    print(f"摘要: {p['summary'][:200]}...\n")