// Aliases must match MODEL_REGISTRY keys in backend/config/settings.py
export const MODELS = [
  { id: 'llama', label: 'Llama 3.1',   badge: 'Local' },
  { id: 'qwen',  label: 'Qwen 2.5 3B', badge: 'Fast'  },
]
export const MAX_RAG_SOURCES   = 5
export const MAX_MESSAGES      = 500
export const MAX_INPUT_CHARS   = 4000      // backend QueryRequest.query limit
export const MAX_NOTE_CHARS    = 2000      // backend NoteRequest / encounters.store.MAX_NOTE_CHARS
export const MAX_LICENSE_CHARS = 300      // mirrors backend knowledge/ingest.py
export const MAX_ORIGIN_CHARS = 1000
export const MAX_LABEL_CHARS   = 80        // backend EncounterCreate.label limit
export const MAX_UPLOAD_BYTES  = 50 * 1024 ** 2   // backend MAX_DOC_BYTES (50 MB)
export const REQUEST_TIMEOUT_MS = 180_000  // local CPU models can be slow; generation is streamed
export const LS_SCHEMA_VERSION = 4         // bumping clears legacy 'rag_*' localStorage (old chat history)
export const LS_MODEL_KEY      = 'rag_model_v4'
export const SS_ENCOUNTERS_KEY = 'rag_encounters_v1'   // sessionStorage: ids + secret tokens, never chat text

// Reference-document upload (POST /sources)
export const ACCEPTED_DOC_TYPES = ['.pdf', '.txt', '.md', '.markdown', '.csv', '.json']
export const CATEGORIES = [
  { id: '',          label: 'Auto-detect (documents: none)' },
  { id: 'medicine',  label: 'Medicines' },
  { id: 'equipment', label: 'Medical equipment' },
  { id: 'symptom',   label: 'Symptoms' },
  { id: 'other',     label: 'Other' },
]

export const WORKFLOW_LABELS = {
  medicine:  'Medicine reference',
  equipment: 'Equipment reference',
  symptom:   'Symptom reference',
  general:   'General reference',
}

export const STATUS_LABELS = {
  answered:              { label: 'Answered from sources',            tone: 'ok' },
  unverified:            { label: 'Evidence check failed — verify',   tone: 'bad' },
  insufficient_evidence: { label: 'Not in the knowledge base',        tone: 'warn' },
  records_only:          { label: 'Structured record only',           tone: 'info' },
}

// Example questions use SYNTHETIC names only until real reference material has been ingested.
export const SUGGESTION_PROMPTS = [
  'What is the maximum dose of <medicine name>?',
  'What are the contraindications of <medicine name>?',
  'How often should <equipment name> be calibrated?',
  'What does the reference say about <symptom>?',
]

export const ERROR_MESSAGES = {
  NETWORK:   'Cannot reach the backend. Is it running (uvicorn Main:app --port 8000)?',
  TIMEOUT:   'The request timed out — the local model may be slow or busy.',
  SERVER:    'The backend reported an error.',
  ABORTED:   'Generation stopped.',
  UNKNOWN:   'Something went wrong. Please try again.',
  OLLAMA:    'The local model server (Ollama) is not reachable. Start it with: ollama serve',
  GONE:      'This encounter no longer exists on the server (erased or expired). Start a new encounter.',
  BAD_EVENT: 'The server sent a malformed response.',
}
