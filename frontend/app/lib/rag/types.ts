export interface User {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Document {
  id: number;
  user_id: number;
  original_filename: string;
  storage_key: string;
  storage_url: string;
  mime_type: string;
  file_size: number;
  status: "uploaded" | "processing" | "completed" | "failed";
  chunk_count?: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentStatusResponse {
  document_id: number;
  status: "uploaded" | "processing" | "completed" | "failed";
}

export interface SourceCitation {
  text: string;
  document_id: number;
  page_number: number;
  chunk_id: number | null;
  confidence: number | null;
}

export interface RagResponse {
  query: string;
  answer: string | null;
  citations: SourceCitation[];
  sources: SourceChunk[];
  abstained: boolean;
  abstention_reason: string | null;
  abstention_suggestion: string | null;
  confidence: number | null;
}

export interface SourceChunk {
  document_id: number;
  page_number: number;
  content: string;
  score: number;
}

export interface Conversation {
  id: number;
  user_id: number;
  title: string;
  document_ids: number[] | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface Message {
  id: number;
  conversation_id: number;
  role: string;
  content: string;
  abstained: boolean | null;
  abstention_reason: string | null;
  confidence: number | null;
  created_at: string;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
  offset: number;
  limit: number;
}

export interface UsageResponse {
  user_id: number;
  documents_uploaded: number;
  document_quota: number;
  chunks_stored: number;
  chunk_quota: number;
  queries_this_month: number;
  query_quota: number;
}

export interface ApiError {
  status_code: number;
  message: string;
}
