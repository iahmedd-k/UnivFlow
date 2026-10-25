import {
  getRagDocuments,
  uploadRagDocument,
  getRagDocumentStatus,
  deleteRagDocument,
  ragChat,
  ragSearch,
  getRagConversations,
  createRagConversation,
  getRagConversation,
  updateRagConversation,
  deleteRagConversation,
  getRagUsage,
} from "@/app/lib/api";

export type Document = {
  id: number;
  original_filename: string;
  file_size: number;
  status: string;
  created_at: string;
  updated_at: string;
};

export type DocumentStatusResponse = {
  document_id: number;
  status: string;
};

export type Conversation = {
  id: number;
  user_id: number;
  title: string;
  document_ids: number[] | null;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = {
  id: number;
  user_id: number;
  title: string;
  document_ids: number[] | null;
  created_at: string;
  updated_at: string;
  messages: Array<{
    id: number;
    conversation_id: number;
    role: string;
    content: string;
    abstained?: boolean | null;
    abstention_reason?: string | null;
    confidence?: number | null;
    created_at: string;
  }>;
};

export type ConversationListResponse = {
  conversations: Conversation[];
  total: number;
  offset: number;
  limit: number;
};

export type RagResponse = {
  query: string;
  answer: string | null;
  citations: Array<{
    text: string;
    document_id: number;
    page_number: number;
    chunk_id: number | null;
    confidence: number | null;
  }>;
  sources: Array<{
    document_id: number;
    page_number: number;
    content: string;
    score: number;
  }>;
  abstained: boolean;
  abstention_reason: string | null;
  abstention_suggestion: string | null;
  confidence: number | null;
};

export type UsageResponse = {
  user_id: number;
  documents_uploaded: number;
  document_quota: number;
  chunks_stored: number;
  chunk_quota: number;
  queries_this_month: number;
  query_quota: number;
};

/* ── Documents ──────────────────────────────────────────────────────── */

export async function listDocuments(): Promise<Document[]> {
  const res = await getRagDocuments();
  return res?.data ?? res ?? [];
}

export async function uploadDocument(file: File): Promise<Document> {
  const res = await uploadRagDocument(file);
  return res?.data ?? res;
}

export async function getDocumentStatus(documentId: number): Promise<DocumentStatusResponse> {
  const res = await getRagDocumentStatus(documentId);
  return res?.data ?? res;
}

export async function deleteDocument(documentId: number): Promise<void> {
  await deleteRagDocument(documentId);
}

/* ── Conversations ──────────────────────────────────────────────────── */

export async function listConversations(offset = 0, limit = 50): Promise<ConversationListResponse> {
  const res = await getRagConversations(undefined, offset, limit);
  return res?.data ?? res ?? { conversations: [], total: 0, offset, limit };
}

export async function createConversation(title?: string, documentIds?: number[]): Promise<Conversation> {
  const res = await createRagConversation({ title: title || "New Conversation", document_ids: documentIds || null });
  return res?.data ?? res;
}

export async function getConversation(conversationId: number): Promise<ConversationDetail> {
  const res = await getRagConversation(conversationId);
  return res?.data ?? res;
}

export async function updateConversationTitle(conversationId: number, title: string): Promise<Conversation> {
  const res = await updateRagConversation(conversationId, { title });
  return res?.data ?? res;
}

export async function deleteConversation(conversationId: number): Promise<void> {
  await deleteRagConversation(conversationId);
}

/* ── Chat / RAG ─────────────────────────────────────────────────────── */

export interface ChatRequest {
  query: string;
  conversation_id?: number | null;
  document_ids?: number[] | null;
  top_k?: number;
}

export async function sendChat(request: ChatRequest): Promise<RagResponse> {
  const res = await ragChat(request);
  return res?.data ?? res;
}

export async function getUsage(): Promise<UsageResponse> {
  const res = await getRagUsage();
  return res?.data ?? res;
}
