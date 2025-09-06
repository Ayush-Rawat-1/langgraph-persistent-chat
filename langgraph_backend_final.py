import os
from dotenv import load_dotenv
load_dotenv()
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict,Annotated
from langchain_core.messages import AnyMessage,SystemMessage,HumanMessage,AIMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode,tools_condition
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_core.tools import tool
import sqlite3
import requests
from typing import Deque,Literal
from collections import deque

# llm
groq_api_key = os.getenv("GROQ_API_KEY")
llm=ChatGroq(model_name="openai/gpt-oss-20b",groq_api_key=groq_api_key)

# Tools
search_wrapper = DuckDuckGoSearchAPIWrapper(region='us-en')
search_tool = DuckDuckGoSearchRun(api_wrapper=search_wrapper)

@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression using python eval function and return the result as a string.
    
    Example:
        calculator("2 + 3 * (4 - 1)")
    """
    try:
        # Safe evaluation using Python's eval with restricted globals
        result = eval(expression, {"__builtins__": {}}, {})
        return {"expression":expression,"result":str(result)}
    except Exception as e:
        return {"error": {str(e)}}

@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA') 
    using Alpha Vantage with API key in the URL.
    """
    alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY")
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={alpha_vantage_api_key}"
    r = requests.get(url)
    return r.json()

tools = [search_tool, get_stock_price, calculator]
llm_with_tools = llm.bind_tools(tools)
tool_node = ToolNode(tools)


class ChatState(TypedDict):
    """State of chatbot, append each message(system,human,ai)"""
    messages: Annotated[list[AnyMessage], add_messages]
    metadata: dict # <-- field for title (optional, will be created when needed)

def chat_node(state: ChatState):

    # take user query from state
    messages = state['messages']

    # send to llm
    response = llm_with_tools.invoke(messages)

    # response store state
    return {'messages': [response]}

def title_node(state: ChatState):
    # generates a title based on the first user query
    user_message = next(
        (m.content for m in state['messages'] if isinstance(m, HumanMessage)), ''
    )
    if not user_message:
        return {}

    title_prompt = f'Generate a very short, 3-6 word title summarizing this query:\n\n{user_message}'
    title = llm.invoke([HumanMessage(content=title_prompt)]).content
    
    return {'metadata': {'title': title}}

def title_condition(state: ChatState)-> Literal['title_node','end']:
    """Decide whether to trigger the `title_node` after a chat turn."""
    if 'title' not in state.get('metadata',{}):
        return 'title_node'
    return 'end'

# checkpointer for persistance
conn = sqlite3.connect(database='chatbot.sqlite', check_same_thread=False)
# Checkpointer
checkpointer = SqliteSaver(conn=conn)

graph = StateGraph(ChatState)

# add nodes
graph.add_node('chat_node', chat_node)
graph.add_node('tools',tool_node)
graph.add_node('title_node', title_node)

graph.add_edge(START, 'chat_node')
graph.add_conditional_edges( 'chat_node',tools_condition)
graph.add_edge('tools','chat_node')
graph.add_conditional_edges('chat_node',title_condition,{'title_node':'title_node','end':END})
graph.add_edge('title_node', 'chat_node') 

chatbot = graph.compile(checkpointer=checkpointer)

def retrieve_all_threads()->Deque[str]:
    """
    Retrieve all unique thread IDs.
    Returns a deque of str like:
    ['thr-1', .... ]
    """
    used_threads = set()
    all_threads = deque()
    for checkpoint in checkpointer.list(None):
        thread_id=checkpoint.config['configurable']['thread_id']
        if thread_id not in used_threads:
            used_threads.add(thread_id)
            all_threads.append(thread_id)

    return all_threads

def retrieve_all_threads_with_titles() -> Deque[dict]:
    """
    Retrieve all unique thread IDs with their generated titles (if available).
    Returns a deque of dicts like:
    [{'thread_id': 'thr-1', 'title': 'Trending Sports News'}, ...]
    """
    used_threads = set()
    all_threads = deque()

    for checkpoint in checkpointer.list(None):
        thread_id = checkpoint.config['configurable']['thread_id']
        # print(checkpoint.checkpoint['channel_values']['metadata'])
        metadata = checkpoint.checkpoint.get('channel_values', {}).get('metadata', {})
        title = metadata.get('title')
        
        if thread_id not in used_threads and title:
            used_threads.add(thread_id)
            all_threads.append({'thread_id': thread_id, 'title': title})

    return all_threads
