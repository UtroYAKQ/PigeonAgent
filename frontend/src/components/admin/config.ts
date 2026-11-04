export type AdminConfigCategory =
  | 'site'
  | 'deepseek'
  | 'sandbox'
  | 'email'
  | 'files'
  | 'logging'
  | 'features'

export const CONFIG_GROUP_LAYOUT: Record<AdminConfigCategory, { title: string; keys: string[] }[]> = {
  site: [{ title: '品牌信息', keys: ['site_name', 'site_description', 'site_logo_url'] }],
  deepseek: [
    { title: '凭证', keys: ['deepseek_api_key', 'deepseek_api_base'] },
    { title: '请求超时', keys: ['deepseek_search_timeout_seconds', 'deepseek_fetch_timeout_seconds'] },
  ],
  sandbox: [
    { title: '连接', keys: ['sandbox_api_key', 'sandbox_api_url', 'sandbox_domain', 'sandbox_template'] },
    { title: '运行策略', keys: ['sandbox_idle_seconds', 'workspace_root'] },
  ],
  email: [
    { title: 'SMTP', keys: ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_tls', 'email_from'] },
    { title: '注册验证', keys: ['email_verification_required'] },
  ],
  files: [{ title: '上传限制', keys: ['max_upload_bytes'] }],
  features: [
    {
      title: '能力开关',
      keys: [
        'feature_web_search_enabled',
        'feature_image_generation_enabled',
        'feature_sandbox_enabled',
      ],
    },
  ],
  logging: [
    { title: '采集范围', keys: ['operation_log_enabled', 'operation_log_trust_proxy', 'operation_log_exclude_paths'] },
    { title: '异步队列', keys: ['operation_log_queue_max', 'operation_log_batch_size', 'operation_log_flush_ms'] },
    { title: '体积与保留', keys: ['operation_log_max_request_body', 'operation_log_max_response_body', 'operation_log_retention_days'] },
  ],
}
