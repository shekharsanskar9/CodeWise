"""
CodeWise - Intelligent Code Mentor AI
Backend server with RAG capabilities powered by Ollama
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from pathlib import Path
import ollama
import chromadb
import uuid
from datetime import datetime
import hashlib

app = Flask(__name__)
CORS(app)

# Initialize Chroma vector database
chroma_client = chromadb.PersistentClient(
    path="./chroma_data"
)

# Define your Ollama model here
OLLAMA_MODEL = "qwen2.5-coder:7b"

# Store collections and metadata
collections_metadata = {}
UPLOAD_FOLDER = "./uploaded_files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', 
                        '.cs', '.go', '.rb', '.php', '.swift', '.kt', '.rs', '.txt',
                        '.md', '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.sql'}


def get_file_type(filename):
    """Determine file type from extension"""
    ext = Path(filename).suffix.lower()
    if ext in {'.py'}:
        return 'python'
    elif ext in {'.js', '.jsx', '.ts', '.tsx'}:
        return 'javascript'
    elif ext in {'.java'}:
        return 'java'
    elif ext in {'.cpp', '.c'}:
        return 'cpp'
    elif ext in {'.cs'}:
        return 'csharp'
    elif ext in {'.go'}:
        return 'golang'
    elif ext in {'.md', '.txt'}:
        return 'text'
    else:
        return 'code'


def chunk_code(content, filename, chunk_size=1000, overlap=200):
    """Split code into intelligent chunks with context"""
    chunks = []
    lines = content.split('\n')
    
    current_chunk = []
    current_size = 0
    
    for i, line in enumerate(lines):
        current_chunk.append(line)
        current_size += len(line)
        
        if current_size >= chunk_size or i == len(lines) - 1:
            chunk_text = '\n'.join(current_chunk)
            chunks.append({
                'content': chunk_text,
                'filename': filename,
                'start_line': max(0, i - len(current_chunk) + 1),
                'end_line': i,
                'file_type': get_file_type(filename)
            })
            
            # Overlap for context
            overlap_lines = min(len(current_chunk), overlap // 30)
            current_chunk = current_chunk[-overlap_lines:] if overlap_lines > 0 else []
            current_size = sum(len(line) for line in current_chunk)
    
    return chunks


def process_uploaded_file(file, project_id):
    """Process and store uploaded file"""
    if file.filename == '':
        return None, "No file selected"
    
    # Check file extension
    if Path(file.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None, f"Unsupported file type: {Path(file.filename).suffix}"
    
    try:
        content = file.read().decode('utf-8', errors='ignore')
        
        # Chunk the file
        chunks = chunk_code(content, file.filename)
        
        # Get or create collection
        collection_name = f"project_{project_id}"
        try:
            collection = chroma_client.get_collection(collection_name)
        except:
            collection = chroma_client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        
        # Add chunks to collection
        for i, chunk in enumerate(chunks):
            chunk_id = f"{project_id}_{hashlib.md5(chunk['content'].encode()).hexdigest()}"
            
            collection.add(
                ids=[chunk_id],
                documents=[chunk['content']],
                metadatas=[{
                    'filename': chunk['filename'],
                    'start_line': chunk['start_line'],
                    'end_line': chunk['end_line'],
                    'file_type': chunk['file_type']
                }]
            )
        
        # Update metadata
        if project_id not in collections_metadata:
            collections_metadata[project_id] = {
                'files': [],
                'created_at': datetime.now().isoformat(),
                'total_lines': 0
            }
        
        collections_metadata[project_id]['files'].append({
            'filename': file.filename,
            'chunks': len(chunks),
            'size': len(content),
            'uploaded_at': datetime.now().isoformat()
        })
        
        collections_metadata[project_id]['total_lines'] += len(content.split('\n'))
        
        return True, f"Successfully processed {file.filename} with {len(chunks)} chunks"
    
    except Exception as e:
        return False, f"Error processing file: {str(e)}"


def retrieve_relevant_context(project_id, query, top_k=5):
    """Retrieve relevant code chunks using semantic search"""
    try:
        collection_name = f"project_{project_id}"
        collection = chroma_client.get_collection(collection_name)
        
        results = collection.query(
            query_texts=[query],
            n_results=top_k
        )
        
        context_chunks = []
        if results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] and results['metadatas'][0] else {}
                context_chunks.append({
                    'content': doc,
                    'filename': metadata.get('filename', 'unknown'),
                    'lines': f"{metadata.get('start_line', 0)}-{metadata.get('end_line', 0)}",
                    'relevance': results['distances'][0][i] if results['distances'] else 0
                })
        
        return context_chunks
    
    except Exception as e:
        print(f"Retrieval error: {str(e)}")
        return []


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


@app.route('/api/projects/create', methods=['POST'])
def create_project():
    """Create a new project"""
    try:
        project_id = str(uuid.uuid4())
        collections_metadata[project_id] = {
            'files': [],
            'created_at': datetime.now().isoformat(),
            'total_lines': 0
        }
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'message': 'Project created successfully'
        }), 201
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<project_id>/upload', methods=['POST'])
def upload_files(project_id):
    """Upload files to a project"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        results = []
        
        for file in files:
            success, message = process_uploaded_file(file, project_id)
            results.append({
                'filename': file.filename,
                'success': success,
                'message': message
            })
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'uploads': results,
            'metadata': collections_metadata.get(project_id, {})
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<project_id>/ask', methods=['POST'])
def ask_question(project_id):
    """Ask a question about the project codebase"""
    try:
        data = request.json
        question = data.get('question', '')
        conversation_history = data.get('history', [])
        
        if not question:
            return jsonify({'success': False, 'error': 'Question is required'}), 400
        
        # Retrieve relevant context
        relevant_chunks = retrieve_relevant_context(project_id, question, top_k=5)
        
        # Build context string
        context_str = "## Relevant Code Sections\n\n"
        for chunk in relevant_chunks:
            context_str += f"**File: {chunk['filename']} (Lines {chunk['lines']})**\n```\n{chunk['content']}\n```\n\n"
        
        # Build system prompt
        system_prompt = """You are CodeWise, an expert code mentor AI. Your role is to:
1. Analyze code shared with you
2. Answer questions about code architecture, functionality, and best practices
3. Provide constructive criticism and improvement suggestions
4. Explain complex code in simple terms
5. Suggest optimizations and refactorings

Be professional, concise, and specific. Always reference file names and line numbers when relevant."""
        
        # Initialize messages with System Prompt (supported by Ollama)
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add conversation history
        for msg in conversation_history[-5:]:  # Keep last 5 for context
            messages.append({
                "role": msg.get('role', 'user'),
                "content": msg.get('content', '')
            })
        
        # Add current question with context
        messages.append({
            "role": "user",
            "content": f"{context_str}\n\nQuestion: {question}"
        })
        
        # Call Ollama API
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=messages
        )
        
        answer = response["message"]["content"]
        
        return jsonify({
            'success': True,
            'question': question,
            'answer': answer,
            'sources': [
                {
                    'filename': chunk['filename'],
                    'lines': chunk['lines']
                }
                for chunk in relevant_chunks
            ],
            'model': OLLAMA_MODEL,
            'usage': {
                'input_tokens': response.get('prompt_eval_count', 0),
                'output_tokens': response.get('eval_count', 0)
            }
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<project_id>/analyze', methods=['GET'])
def analyze_project(project_id):
    """Get AI-powered analysis of the project"""
    try:
        metadata = collections_metadata.get(project_id)
        if not metadata:
            return jsonify({'success': False, 'error': 'Project not found'}), 404
        
        # Retrieve sample chunks for analysis
        collection_name = f"project_{project_id}"
        collection = chroma_client.get_collection(collection_name)
        
        results = collection.get(limit=10)
        
        sample_code = "\n\n".join(results['documents'][:5]) if results['documents'] else ""
        
        system_prompt = """You are a code analysis expert. Analyze the provided code sample and provide:
1. Overall architecture overview
2. Key patterns and technologies used
3. Code quality assessment
4. Potential improvements
5. Security considerations

Be concise but thorough."""
        
        # Call Ollama API
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this project code:\n\n{sample_code}"}
            ]
        )
        
        analysis = response["message"]["content"]
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'metadata': metadata,
            'analysis': analysis
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/projects/<project_id>/info', methods=['GET'])
def get_project_info(project_id):
    """Get project information"""
    try:
        metadata = collections_metadata.get(project_id)
        if not metadata:
            return jsonify({'success': False, 'error': 'Project not found'}), 404
        
        return jsonify({
            'success': True,
            'project_id': project_id,
            'metadata': metadata
        }), 200
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)