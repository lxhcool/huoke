export type SearchRequest = {
  query: string;
  sources: string[];
  country?: string;
  hs_code?: string;
  customer_profile_mode: string;
  customs_required: boolean;
  limit: number;
};

export type ContactItem = {
  name: string;
  title: string;
  email?: string | null;
  email_type?: string | null;
  confidence: string;
};

export type CustomsSummary = {
  active_label: string;
  last_trade_at: string;
  hs_code?: string | null;
  frequency: number;
};

export type LeadItem = {
  company_id: number;
  company_name: string;
  country: string;
  city?: string | null;
  website?: string | null;
  industry?: string | null;
  score: number;
  confidence: string;
  match_reasons: string[];
  contacts: ContactItem[];
  customs_summary?: CustomsSummary | null;
};

export type SearchResponse = {
  parsed_query: {
    original_query: string;
    normalized_keywords: string[];
    country?: string | null;
    hs_code?: string | null;
    customer_profile_mode: string;
    customs_required: boolean;
    limit: number;
  };
  total: number;
  items: LeadItem[];
};

export type SourceTask = {
  id: number;
  source_name: string;
  task_type: string;
  status: string;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type SearchJob = {
  id: number;
  query: string;
  country?: string | null;
  hs_code?: string | null;
  customer_profile_mode: string;
  customs_required: boolean;
  limit: number;
  status: string;
  sources: string[];
  result_count: number;
  created_at: string;
  updated_at: string;
  source_tasks: SourceTask[];
};

export type SearchJobResult = {
  id: number;
  company_id: number;
  company_name: string;
  country: string;
  city?: string | null;
  website?: string | null;
  industry?: string | null;
  score: number;
  confidence: string;
  result_status: string;
  intent_label?: string | null;
  source_names: string[];
  match_reasons: string[];
  contacts: ContactItem[];
  customs_summary?: CustomsSummary | null;
};

export type SearchJobResultsResponse = {
  job_id: number;
  status: string;
  total: number;
  items: SearchJobResult[];
};

export type FeedbackRequest = {
  company_id: number;
  action: string;
  user_name?: string;
  query_text?: string;
  note?: string;
};

export type SourceCredentialField = {
  name: string;
  label: string;
  input_type: "text" | "password";
  required: boolean;
};

export type SourceAuthProvider = {
  source_name: string;
  display_name: string;
  task_sources: string[];
  credential_fields: SourceCredentialField[];
};

export type SourceAuthProviderListResponse = {
  items: SourceAuthProvider[];
};

export type SourceAuthVerifyResponse = {
  source_name: string;
  status: "verified" | "failed";
  message: string;
  verified_at: string;
  storage_state_path: string;
};
