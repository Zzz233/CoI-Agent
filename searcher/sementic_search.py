import requests
import json
import yaml
import scipdf
import os
import time
import aiohttp
import asyncio
import numpy as np


def get_content_between_a_b(start_tag, end_tag, text):
    extracted_text = ""
    start_index = text.find(start_tag)
    while start_index != -1:
        end_index = text.find(end_tag, start_index + len(start_tag))
        if end_index != -1:
            extracted_text += text[start_index + len(start_tag) : end_index] + " "
            start_index = text.find(start_tag, end_index + len(end_tag))
        else:
            break
    return extracted_text.strip()


def extract(text, type):
    if text:
        target_str = get_content_between_a_b(f"<{type}>", f"</{type}>", text)
        if target_str:
            return target_str
        else:
            return text
    else:
        return ""


async def fetch(url):
    time.sleep(1)
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()  # Read the response content as bytes
                    return content
                else:
                    await asyncio.sleep(0.01)
                    print(f"Failed to fetch the URL: {url}")
                    return None
    except Exception as e:
        await asyncio.sleep(0.01)
        print(f"An error occurred while fetching the URL: {url}")
        print(e)
        return None
    
class Result:
    def __init__(self,title="",abstract="",pdf_link="",citations_conut = 0,year = None) -> None:
        self.title = title
        self.abstract = abstract
        self.pdf_link = pdf_link
        self.citations_conut = citations_conut
        self.year = year

# Load the API key from the configuration file 
with open('config.yaml') as f:
   config = yaml.load(f, Loader=yaml.FullLoader)
   api_key = config['SEMENTIC_SEARCH_API_KEY'] if 'SEMENTIC_SEARCH_API_KEY' in config else None
   if api_key == "":
      api_key = None
headers = {'x-api-key': api_key} if api_key else None

# Define the API endpoint URL

semantic_fields = ["title", "abstract", "year", "authors.name", "authors.paperCount", "authors.citationCount","authors.hIndex","url","referenceCount","citationCount","influentialCitationCount","isOpenAccess","openAccessPdf","fieldsOfStudy","s2FieldsOfStudy","embedding.specter_v1","embedding.specter_v2","publicationDate","citations"]


fieldsOfStudy = ["Computer Science","Medicine","Chemistry","Biology","Materials Science","Physics","Geology","Art","History","Geography","Sociology","Business","Political Science","Philosophy","Art","Literature","Music","Economics","Philosophy","Mathematics","Engineering","Environmental Science","Agricultural and Food Sciences","Education","Law","Linguistics"]

# citations.paperId, citations.title, citations.year, citations.authors.name, citations.authors.paperCount, citations.authors.citationCount, citations.authors.hIndex, citations.url, citations.referenceCount, citations.citationCount, citations.influentialCitationCount, citations.isOpenAccess, citations.openAccessPdf, citations.fieldsOfStudy, citations.s2FieldsOfStudy, citations.publicationDate

# publicationDateOrYear： 2019-03-05 ； 2019-03 ； 2019 ； 2016-03-05:2020-06-06 ； 1981-08-25: ； :2020-06-06 ； 1981:2020

# publicationTypes: Review ； JournalArticle CaseReport ； ClinicalTrial ； Dataset ； Editorial ； LettersAndComments ； MetaAnalysis ； News ； Study ； Book ； BookSection



def process_fields(fields):
   return ",".join(fields)


class SementicSearcher:
    def __init__(self, save_file = "papers/",ban_paper = []) -> None:
        self.save_file = save_file
        self.ban_paper = ban_paper
    
    async def search_papers_async(self, query, limit=5, offset=0, fields=["title", "paperId", "abstract", "isOpenAccess", 'openAccessPdf', "year","publicationDate","citations.title","citations.abstract","citations.isOpenAccess","citations.openAccessPdf","citations.citationCount","citationCount","citations.year"],
                            publicationDate=None, minCitationCount=0, year=None, 
                            publicationTypes=None, fieldsOfStudy=None):
        url = 'https://api.semanticscholar.org/graph/v1/paper/search'
        fields = process_fields(fields) if isinstance(fields, list) else fields
        
        # More specific query parameter
        query_params = {
            'query': query,
            "limit": limit,
            "offset": offset,
            'fields': fields,
            'publicationDateOrYear': publicationDate,
            'minCitationCount': minCitationCount,
            'year': year,
            'publicationTypes': publicationTypes,
            'fieldsOfStudy': fieldsOfStudy
        }
        await asyncio.sleep(0.5)
        try:
            filtered_query_params = {key: value for key, value in query_params.items() if value is not None}
            response = requests.get(url, params=filtered_query_params, headers=headers)

            if response.status_code == 200:
                response_data = response.json()
                return response_data
            elif response.status_code == 429:
                time.sleep(1)  
                print(f"Request failed with status code {response.status_code}: begin to retry")
                return await self.search_papers_async(query, limit, offset, fields, publicationDate, minCitationCount, year, publicationTypes, fieldsOfStudy)
            else:
                print(f"Request failed with status code {response.status_code}: {response.text}")
                return None
        except requests.RequestException as e:
            print(f"An error occurred: {e}")
            return None
                
    def cal_cosine_similarity(self, vec1, vec2):
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

    def read_arxiv_from_path(self, pdf_path):
        if not os.path.exists(pdf_path):
            print(f"The PDF file <{pdf_path}> does not exist.")
            return None
        article_dict = scipdf.parse_pdf_to_dict(pdf_path)
        return article_dict
        
    async def get_paper_embbeding_and_score_async(self,query_embedding, paper,llm):
        paper_content = f"""
Title: {paper['title']}
Abstract: {paper['abstract']}
"""
        paper_embbeding = await llm.get_embbeding_async(paper_content)
        paper_embbeding = np.array(paper_embbeding)
        score = self.cal_cosine_similarity(query_embedding,paper_embbeding)
        return [paper,score]

    
    async def rerank_papers_async(self, query_embedding, paper_list,llm):
        if len(paper_list) >= 50:
            paper_list = paper_list[:50]
        results = await asyncio.gather(*[self.get_paper_embbeding_and_score_async(query_embedding, paper,llm) for paper in paper_list if paper])
        reranked_papers = sorted(results,key = lambda x: x[1],reverse = True)
        return reranked_papers
    
    async def get_embbeding_and_score_async(self,query_embedding, text,llm):
        text_embbeding = await llm.get_embbeding_async(text)
        text_embbeding = np.array(text_embbeding)
        score = self.cal_cosine_similarity(query_embedding,text_embbeding)
        return score
    
    async def get_embbeding_and_score_from_texts_async(self,query_embedding, texts,llm):
        results = await asyncio.gather(*[self.get_embbeding_and_score_async(query_embedding, text,llm) for text in texts])
        return results
    
    async def get_paper_details_async(self, paper_id, fields = ["title", "abstract", "year","citationCount","isOpenAccess","openAccessPdf"]):
        url = f'https://api.semanticscholar.org/graph/v1/paper/{paper_id}'
        fields = process_fields(fields)
        paper_data_query_params = {'fields': fields}
        try:
            async with aiohttp.ClientSession() as session:
                filtered_query_params = {key: value for key, value in paper_data_query_params.items() if value is not None}
                async with session.get(url, params=filtered_query_params, headers=headers) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        return response_data
                    else:
                        await asyncio.sleep(0.01)
                        print(f"Request failed with status code {response.status}: {await response.text()}")
                        return None
        except Exception as e:
            print(f"Failed to get paper details for paper ID: {paper_id}")
            return None
    
    async def batch_retrieve_papers_async(self, paper_ids, fields = semantic_fields):
        url = 'https://api.semanticscholar.org/graph/v1/paper/batch'
        paper_data_query_params = {'fields': process_fields(fields)}
        paper_ids_json = {"ids": paper_ids}
        try:
            async with aiohttp.ClientSession() as session:
                filtered_query_params = {key: value for key, value in paper_data_query_params.items() if value is not None}
                async with session.post(url, json=paper_ids_json, params=filtered_query_params, headers=headers) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        return response_data
                    else:
                        await asyncio.sleep(0.01)
                        print(f"Request failed with status code {response.status}: {await response.text()}")
                        return None
        except Exception as e:
            print(f"Failed to batch retrieve papers for paper IDs: {paper_ids}")
            return None
    
    async def search_paper_from_title_async(self, query,fields = ["title","paperId"]):
        url = 'https://api.semanticscholar.org/graph/v1/paper/search/match'
        fields = process_fields(fields)
        query_params = {'query': query, 'fields': fields}
        try:
            async with aiohttp.ClientSession() as session:
                filtered_query_params = {key: value for key, value in query_params.items() if value is not None}
                async with session.get(url, params=filtered_query_params, headers=headers) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        return response_data
                    else:
                        await asyncio.sleep(0.01)
                        print(f"Request failed with status code {response.status}: {await response.text()}")
                        return None
        except Exception as e:
            await asyncio.sleep(0.01)
            print(f"Failed to search paper from title: {query}")
            return None
        
    
    async def search_async(self,query,max_results = 5 ,paper_list = None ,rerank_query = None,llm = None,year = None,publicationDate = None,need_download = True,fields = ["title", "paperId", "abstract", "isOpenAccess", 'openAccessPdf', "year","publicationDate","citationCount"]):
        if rerank_query:
            rerank_query_embbeding = llm.get_embbeding(rerank_query)
            rerank_query_embbeding = np.array(rerank_query_embbeding)

        readed_papers = []
        if paper_list:
            if isinstance(paper_list,set):
                paper_list = list(paper_list)
            if len(paper_list) == 0 :
                pass
            elif isinstance(paper_list[0], str):
                readed_papers = paper_list
            elif isinstance(paper_list[0], Result):
                readed_papers = [paper.title for paper in paper_list]

        print(f"Searching for papers related to <{query}>")
        results = await self.search_papers_async(query,limit = 30,year=year,publicationDate = publicationDate,fields = fields)
        if not results or "data" not in results:
            return []
        
        new_results = []
        for result in results['data']:
            if result['title'] in self.ban_paper:
                continue
            new_results.append(result)
        results = new_results

        final_results = []
        if need_download:
            paper_candidates = []
            for result in results:
                if os.path.exists(os.path.join(self.save_file, f"{result['title']}.pdf")) and result['title'] not in readed_papers:
                    paper_candidates.append(result)
                elif not result['isOpenAccess'] or  not result['openAccessPdf'] or result['title'] in readed_papers:
                    continue
                else:
                    paper_candidates.append(result)
        else:
            paper_candidates = results
        
        if llm and rerank_query:
            paper_candidates = await self.rerank_papers_async(rerank_query_embbeding, paper_candidates,llm)
            paper_candidates = [paper[0] for paper in paper_candidates if paper]
        
        if need_download:
            for result in paper_candidates:
                if not os.path.exists(os.path.join(self.save_file, f"{result['title']}.pdf")):
                    pdf_link = result['openAccessPdf']["url"]
                    try:
                        flag = await self.download_pdf_async(pdf_link, f"{result['title']}.pdf")
                        if not flag:
                            continue
                    except Exception as e:
                        continue
                title = result['title']
                abstract = result['abstract']
                citationCount = result['citationCount']
                pdf_link = None
                year = result['year']
                final_results.append(Result(title,abstract,pdf_link,citationCount,year))
                if len(final_results) >= max_results:
                    break
        else:
            for result in paper_candidates:
                title = result['title']
                abstract = result['abstract']
                citationCount = result['citationCount']
                year = result['year']
                final_results.append(Result(title,abstract,None,citationCount,year))
                if len(final_results) >= max_results:
                    break
        return final_results
    
    async def search_paper_cited_by_async(self,title,rerank_query,llm,paper_list = []):
        print(f"Searching for papers cited by <{title}>")
        results = await self.search_papers_async(title,limit = 5)
        citations = []
        if not results or "data" not in results:
            return None
        for result in results["data"]:
            for citation in result["citations"]:
                if os.path.exists(os.path.join(self.save_file, f"{citation['title']}.pdf")) and citation["title"] not in paper_list:
                    citations.append(citation)
                elif citation["title"] in self.ban_paper or citation["isOpenAccess"] == False or citation["openAccessPdf"] == None or citation["abstract"] == None or citation["title"] in paper_list:
                    continue
                else:
                    citations.append(citation)

        if len(citations) >= 200:
            import random
            citations = random.sample(citations,50)

        if llm and rerank_query:
            rerank_query_embbeding = llm.get_embbeding(rerank_query)
            rerank_query_embbeding = np.array(rerank_query_embbeding)
            citations = await self.rerank_papers_async(rerank_query_embbeding, citations,llm)
            citations = [citation[0] for citation in citations]

        relevant_citation = None
        
        for citation in citations:
            if os.path.exists(os.path.join(self.save_file, f"{citation['title']}.pdf")):
                relevant_citation = citation
                break
            flag = await self.download_pdf_async(citation["openAccessPdf"]["url"],f"{citation['title']}.pdf")
            if flag:
                citation["pdf_link"] = f"{citation['title']}.pdf"
                relevant_citation = citation
                break
        if not relevant_citation:
            for citation in citations:
                print(citation["title"],end="")
            print(f"No relevant citation found for the paper <{title}>")
            return None
        title = relevant_citation["title"] if "title" in relevant_citation else ""
        abstract = relevant_citation["abstract"] if "abstract" in relevant_citation else ""
        pdf_link = relevant_citation["pdf_link"] if "pdf_link" in relevant_citation else ""
        citationCount = relevant_citation["citationCount"] if "citationCount" in relevant_citation else 0
        year = relevant_citation["year"] if "year" in relevant_citation else None
        result = Result(title,abstract,pdf_link,citationCount,year)
        return result
    
    
    async def search_related_paper_async(self,title,need_citation = True,need_reference = True,rerank_query = None,llm = None,paper_list = []):
        print(f"Searching for papers related to <{title}>")
        fileds = ["title","abstract","citations.title","citations.abstract","citations.citationCount","references.title","references.abstract","references.citationCount","citations.isOpenAccess","citations.openAccessPdf","references.isOpenAccess","references.openAccessPdf","citations.year","references.year"]
        results = await self.search_papers_async(title,limit = 3,fields=fileds)
        related_papers = []
        related_papers_title = []
        if not results or "data" not in results:
            return []
        for result in results["data"]:
            if not result:
                continue
            if need_citation:
                for citation in result["citations"]:
                    if os.path.exists(os.path.join(self.save_file, f"{citation['title']}.pdf")) and citation["title"] not in paper_list:
                        if "openAccessPdf" not in citation or not citation["openAccessPdf"] or "url" not in citation["openAccessPdf"]:
                            citation["openAccessPdf"] = {"url":None}
                        related_papers.append(citation)
                        related_papers_title.append(citation["title"])
                    elif citation["title"] in related_papers_title or citation["title"] in self.ban_paper or citation["title"] in paper_list:
                        continue
                    elif citation["isOpenAccess"] == False or citation["openAccessPdf"] == None:
                        continue
                    else:
                        related_papers.append(citation)
                        related_papers_title.append(citation["title"])
            if need_reference:
                for reference in result["references"]:
                    if os.path.exists(os.path.join(self.save_file, f"{reference['title']}.pdf")) and reference["title"] not in paper_list:
                        if "openAccessPdf" not in reference or not reference["openAccessPdf"] or "url" not in reference["openAccessPdf"]:
                            reference["openAccessPdf"] = {"url":None}
                        related_papers.append(reference)
                        related_papers_title.append(reference["title"])
                    elif reference["title"] in related_papers_title or reference["title"] in self.ban_paper or reference["title"] in paper_list:
                        continue
                    elif reference["isOpenAccess"] == False or reference["openAccessPdf"] == None:
                        continue
                    else:
                        related_papers.append(reference)
                        related_papers_title.append(reference["title"])
            if result:
                break

        if rerank_query and llm:
            rerank_query_embbeding = llm.get_embbeding(rerank_query)
            rerank_query_embbeding = np.array(rerank_query_embbeding)
            related_papers = await self.rerank_papers_async(rerank_query_embbeding, related_papers,llm)
            related_papers = [paper[0] for paper in related_papers]
            related_papers = [Result(paper["title"],paper["abstract"],paper["openAccessPdf"]["url"],paper["citationCount"],paper['year']) for paper in related_papers]
        else:
            related_papers = [[paper["title"],paper["abstract"],paper["openAccessPdf"]["url"],paper["citationCount"],paper['year']] for paper in related_papers]
            related_papers = sorted(related_papers,key = lambda x: x[3],reverse = True)
            related_papers = [Result(paper[0],paper[1],paper[2],paper[3]) for paper in related_papers]
        if len(related_papers) >= 10:
            related_papers = related_papers[:10]
        return related_papers

    
    async def search_paper_for_abstract_async(self,query,fields = ["title","abstract"]):
        arxiv_result = await self.search_paper_from_title_async(query, fields = fields)
        if not arxiv_result or "data" not in arxiv_result:
            print(f"The paper <{query}> is not found.")
            return None
        return arxiv_result['data'][0]


    async def read_abs_from_title(self,title):
        arxiv_result = await self.search_paper_from_title_async(title, fields = ["title","abstract"])
        if not arxiv_result or "data" not in arxiv_result:
            print(f"The paper <{title}> is not found.")
            return None
        abs = arxiv_result['data'][0]['abstract']
        return abs
    
    async def read_arxiv_from_title(self,title):
        arxiv_result = await self.search_paper_from_title_async(title, fields = ["isOpenAccess","openAccessPdf"])
        if not arxiv_result or "data" not in arxiv_result:
            print(f"The paper <{title}> is not found.")
            return None
        isopen = arxiv_result['data'][0]['isOpenAccess']
        pdf_link = arxiv_result['data'][0]['openAccessPdf']
        if not isopen or not pdf_link:
            print(f"The paper <{title}> is not open access.")
            return None
        
        pdf_link = pdf_link["url"]
        result = await self.download_pdf_async(pdf_link, f"{title}.pdf")
        if not result:
            return None
        pdf_path = os.path.join(self.save_file, f"{title}.pdf")
        article_dict = self.read_arxiv_from_path(pdf_path)
        return article_dict    
    
    async def read_arxiv_from_link_async(self, pdf_link , filename):
        result = await self.download_pdf_async(pdf_link, filename)
        if not result:
            await asyncio.sleep(0.01)
            print(f"Failed to download the PDF file: {filename}")
            return None
        try:
            await asyncio.sleep(0.01)
            pdf_path = os.path.join(self.save_file, filename)
            article_dict = self.read_arxiv_from_path(pdf_path)
            return article_dict
        except Exception as e:
            await asyncio.sleep(0.01)
            print(f"Failed to read the article from the PDF file: {e}, {filename}")
            return None

    async def download_pdf_async(self, pdf_link, filename):
        filename = os.path.join(self.save_file, filename)
        await asyncio.sleep(0.01)
        if os.path.exists(filename):
            print(f"The PDF file <{filename}> already exists.")
            return True
        content = await fetch(pdf_link)
        if not content:
            print(f"Failed to download the PDF file: {filename}")
            if "/" in filename:
                filename = filename.split("/")[-1]
            if "." in filename:
                filename = filename.split(".")[0]
            return False
        try:
            with open(filename, 'wb') as file:
                file.write(content)
            return True
        except Exception as e:
            print(f"Failed to download the PDF file: {e}, {filename}")
            if "/" in filename:
                filename = filename.split("/")[-1]
            if "." in filename:
                filename = filename.split(".")[0]
            return False

    def read_paper_title_abstract(self,article):
        title = article["title"]
        abstract = article["abstract"]
        paper_content = f"""
Title: {title}
Abstract: {abstract}
        """
        return paper_content
    
    def read_paper_title_abstract_introduction(self,article):
        title = article["title"]
        abstract = article["abstract"]
        introduction = article["sections"][0]["text"]
        paper_content = f"""
Title: {title}
Abstract: {abstract}
Introduction: {introduction}
        """
        return paper_content

    def read_paper_content(self,article):
        paper_content = self.read_paper_title_abstract(article)
        for section in article["sections"]:
            paper_content += f"section: {section['heading']}\n content: {section['text']}\n ref_ids: {section['publication_ref']}\n"
        return paper_content
    
    def read_paper_content_with_ref(self,article):
        paper_content = self.read_paper_content(article)
        paper_content += "<References>\n"
        i = 1
        for refer in article["references"]:
            ref_id = refer["ref_id"]
            title = refer["title"]
            year = refer["year"]
            paper_content += f"Ref_id:{ref_id} Title: {title} Year: ({year})\n"
            i += 1
        paper_content += "</References>\n"
        return paper_content

        
