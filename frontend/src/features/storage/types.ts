export type StorageType = "s3" | "rados";

export interface StorageProfile {
  id: string;
  name: string;
  storage_type: StorageType;
  description: string;
  enabled: boolean;
  revision: number;
  creator_id: string;
  can_manage: boolean;
  parameters: Record<string, string>;
  has_secrets: boolean;
  created_at: string;
  updated_at: string;
}
