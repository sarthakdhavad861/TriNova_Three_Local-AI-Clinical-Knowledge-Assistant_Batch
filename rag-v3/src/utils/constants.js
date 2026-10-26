// Aliases must match MODEL_REGISTRY keys in backend/config/settings.py
export const MODELS = [
  { id: 'llama', label: 'Llama 3.1',   badge: 'Local' },
  { id: 'qwen',  label: 'Qwen 2.5 3B', badge: 'Fast'  },
]
export const MAX_RAG_SOURCES      = 5
export const MAX_SESSIONS         = 100
export const MAX_MESSAGES         = 500
export const MAX_INPUT_CHARS      = 4000
export const MAX_UPLOAD_BYTES     = 2 * 1024 ** 3
export const CACHE_TTL_MS         = 10 * 60 * 1000
export const REQUEST_TIMEOUT_MS   = 60_000
export const SIMILARITY_THRESHOLD = 0.25
export const TOP_K                = 6
export const LS_SCHEMA_VERSION    = 3
export const SEND_DEBOUNCE_MS     = 400
export const SUGGESTION_PROMPTS = [
  'Explain CSS Flexbox with an example',
  'What is async/await in JavaScript?',
  'How do I center a div in CSS?',
  'Explain the difference between let, const, and var',
  'How does the JavaScript event loop work?',
  'What are React hooks and when should I use them?',
]
export const ACCEPTED_VIDEO_TYPES = ['.mp4', '.mkv', '.mov']
export const ACCEPTED_VIDEO_MIME  = ['video/mp4', 'video/x-matroska', 'video/quicktime']

// v2: PDF support
export const ACCEPTED_PDF_TYPES   = ['.pdf']
export const ACCEPTED_PDF_MIME    = ['application/pdf']

export const ERROR_MESSAGES = {
  NETWORK:     'Network error — check your connection and try again.',
  TIMEOUT:     'Request timed out — the server may be overloaded.',
  SERVER:      'Server error — something went wrong on the backend.',
  RATE_LIMIT:  'Rate limited — please wait a moment and try again.',
  ABORTED:     'Generation stopped.',
  UNKNOWN:     'Something went wrong. Please try again.',
  NO_SCOPE:    'This question is outside the scope of available content.',
  UPLOAD_TYPE: 'Unsupported file type. Please upload .mp4, .mkv, .mov, or .pdf.',
  UPLOAD_SIZE: 'File too large. Maximum size is 2 GB.',
  UPLOAD_MIME: 'File content does not match the expected format.',
}
