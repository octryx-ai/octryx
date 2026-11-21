// Data transfer job and Workspace option shapes of Backup & restore, with the data API base path.
export type ProjectOption = {
  id: string;
  name: string;
};

export type DataTransferJob = {
  id: string;
  status: string;
  export_type?: string;
  import_type?: string;
  file_url?: string | null;
  file_size_bytes?: number | null;
  rows_total?: number;
  rows_success?: number;
  rows_failed?: number;
  summary_json?: Record<string, unknown>;
  error?: string | null;
  errors?: string[];
};

export const DATA = "/api/v1/data";
