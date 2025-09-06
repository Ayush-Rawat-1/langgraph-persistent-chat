import os
from dotenv import load_dotenv
load_dotenv()
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict,Annotated
from langchain_core.messages import AnyMessage,SystemMessage,HumanMessage,AIMessage
from langgraph.graph.message import add_messages
import sqlite3

groq_api_key = os.getenv("GROQ_API_KEY")
llm=ChatGroq(model_name="gemma2-9b-it",groq_api_key=groq_api_key)

class ChatState(TypedDict):
    """State of chatbot, append each message(system,human,ai)"""
    messages: Annotated[list[AnyMessage], add_messages]

def chat_node(state: ChatState):

    # take user query from state
    messages = state['messages']

    # send to llm
    response = llm.invoke(messages)

    # response store state
    return {'messages': [response]}

# checkpointer for persistance
conn = sqlite3.connect(database='chatbot.sqlite', check_same_thread=False)
# Checkpointer
checkpointer = SqliteSaver(conn=conn)

graph = StateGraph(ChatState)

# add nodes
graph.add_node('chat_node', chat_node)

graph.add_edge(START, 'chat_node')
graph.add_edge('chat_node', END)

chatbot = graph.compile(checkpointer=checkpointer)

def retrieve_all_threads():
    all_threads = set()
    for checkpoint in checkpointer.list(None):
        all_threads.add(checkpoint.config['configurable']['thread_id'])

    return list(all_threads)