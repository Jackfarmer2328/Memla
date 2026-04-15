import Foundation

struct MemlaScoutRequest: Codable {
    let prompt: String
}

struct MemlaActionDraftRequest: Codable {
    let prompt: String
}

struct MemlaFollowupRequest: Codable {
    let prompt: String
    let model: String
    let provider: String
    let baseURL: String
    let heuristicOnly: Bool

    enum CodingKeys: String, CodingKey {
        case prompt
        case model
        case provider
        case baseURL = "base_url"
        case heuristicOnly = "heuristic_only"
    }
}

struct MemlaBrowserDebugCandidate: Codable {
    let role: String
    let label: String
    let score: Double
    let groupKey: String
    let groupLabel: String
    let selected: Bool
    let opensSubflow: Bool

    enum CodingKeys: String, CodingKey {
        case role
        case label
        case score
        case groupKey = "group_key"
        case groupLabel = "group_label"
        case selected
        case opensSubflow = "opens_subflow"
    }
}

struct MemlaBrowserDebugRequest: Codable {
    let source: String
    let reason: String
    let title: String
    let url: String
    let pageKind: String
    let pageSummary: String
    let authState: String
    let inspectionStatus: String
    let buttonActionStatus: String
    let autoDriveEnabled: Bool
    let autoDriveStatus: String
    let residuals: [String]
    let safeActions: [String]
    let serviceFacts: [String: String]
    let pendingStep: [String: String]
    let topCandidates: [MemlaBrowserDebugCandidate]
    let agencyTrace: [String]
    let mirrorDebugText: String
    let agencyTraceText: String

    enum CodingKeys: String, CodingKey {
        case source
        case reason
        case title
        case url
        case pageKind = "page_kind"
        case pageSummary = "page_summary"
        case authState = "auth_state"
        case inspectionStatus = "inspection_status"
        case buttonActionStatus = "button_action_status"
        case autoDriveEnabled = "auto_drive_enabled"
        case autoDriveStatus = "auto_drive_status"
        case residuals
        case safeActions = "safe_actions"
        case serviceFacts = "service_facts"
        case pendingStep = "pending_step"
        case topCandidates = "top_candidates"
        case agencyTrace = "agency_trace"
        case mirrorDebugText = "mirror_debug_text"
        case agencyTraceText = "agency_trace_text"
    }
}

struct MemlaAckEnvelope: Codable {
    let ok: Bool
    let message: String?
}

struct MemlaHealthResponse: Codable {
    let ok: Bool
    let service: String
    let runtimeDefaults: RuntimeDefaults

    enum CodingKeys: String, CodingKey {
        case ok
        case service
        case runtimeDefaults = "runtime_defaults"
    }
}

struct RuntimeDefaults: Codable {
    let model: String
    let provider: String
    let heuristicOnly: Bool

    enum CodingKeys: String, CodingKey {
        case model
        case provider
        case heuristicOnly = "heuristic_only"
    }
}

struct MemlaStateEnvelope: Codable {
    let ok: Bool
    let state: BrowserState
}

struct MemlaMemoryEnvelope: Codable {
    let ok: Bool
    let path: String
    let summary: MemorySummary
}

struct MemorySummary: Codable {
    let memoryCount: Int
    let activeCount: Int
    let staleCount: Int
    let invalidCount: Int
    let episodicCount: Int
    let semanticCount: Int
    let ruleCount: Int
    let avgTrust: Double
    let autonomyCount: Int?
    let actionCount: Int?
    let languageCount: Int?
    let kindCounts: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case memoryCount = "memory_count"
        case activeCount = "active_count"
        case staleCount = "stale_count"
        case invalidCount = "invalid_count"
        case episodicCount = "episodic_count"
        case semanticCount = "semantic_count"
        case ruleCount = "rule_count"
        case avgTrust = "avg_trust"
        case autonomyCount = "autonomy_count"
        case actionCount = "action_count"
        case languageCount = "language_count"
        case kindCounts = "kind_counts"
    }
}

struct MemlaActionEnvelope: Codable {
    let ok: Bool
    let summary: ActionSummary
}

struct ActionSummary: Codable {
    let actionCount: Int
    let domains: [String]
    let confirmationRequiredCount: Int
    let implementedCount: Int
    let capabilities: [ActionCapability]

    enum CodingKeys: String, CodingKey {
        case actionCount = "action_count"
        case domains
        case confirmationRequiredCount = "confirmation_required_count"
        case implementedCount = "implemented_count"
        case capabilities
    }
}

struct ActionCapability: Codable, Identifiable {
    var id: String { actionID }

    let actionID: String
    let title: String
    let domain: String
    let description: String
    let riskLevel: String
    let confirmationRequired: Bool
    let status: String

    enum CodingKeys: String, CodingKey {
        case actionID = "action_id"
        case title
        case domain
        case description
        case riskLevel = "risk_level"
        case confirmationRequired = "confirmation_required"
        case status
    }
}

struct MemlaActionDraftEnvelope: Codable {
    let ok: Bool
    let draft: ActionDraft
}

struct MemlaActionCapsuleEnvelope: Codable {
    let ok: Bool
    let capsule: ActionCapsule
}

struct MemlaMissionRequest: Codable {
    let prompt: String
}

struct MemlaMissionDecisionRequest: Codable {
    let decision: String
    let note: String
}

struct MemlaMissionEnvelope: Codable {
    let ok: Bool
    let mission: MemlaMission
}

struct MemlaMissionsEnvelope: Codable {
    let ok: Bool
    let summary: MissionSummary
    let missions: [MemlaMission]
}

struct MissionSummary: Codable {
    let missionCount: Int
    let statusCounts: [String: Int]
    let latestMissionID: String

    enum CodingKeys: String, CodingKey {
        case missionCount = "mission_count"
        case statusCounts = "status_counts"
        case latestMissionID = "latest_mission_id"
    }
}

struct MemlaMission: Codable, Identifiable {
    var id: String { missionID }

    let missionID: String
    let prompt: String
    let title: String
    let actionID: String
    let status: String
    let createdAt: String
    let updatedAt: String
    let capsule: ActionCapsule
    let checkpoint: MissionCheckpoint
    let history: [MissionEvent]

    enum CodingKeys: String, CodingKey {
        case missionID = "mission_id"
        case prompt
        case title
        case actionID = "action_id"
        case status
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case capsule
        case checkpoint
        case history
    }
}

struct MissionCheckpoint: Codable {
    let checkpointID: String
    let kind: String
    let title: String
    let detail: String
    let status: String
    let decisions: [String]
    let safetyLevel: String
    let bridgeOption: ActionBridgeOption?

    enum CodingKeys: String, CodingKey {
        case checkpointID = "checkpoint_id"
        case kind
        case title
        case detail
        case status
        case decisions
        case safetyLevel = "safety_level"
        case bridgeOption = "bridge_option"
    }
}

struct MissionEvent: Codable, Identifiable {
    var id: String { "\(timestamp)-\(kind)-\(detail)" }

    let timestamp: String
    let kind: String
    let detail: String
}

struct ActionDraft: Codable, Identifiable {
    var id: String { "\(actionID)-\(draftText)" }

    let prompt: String
    let ok: Bool
    let actionID: String
    let title: String
    let domain: String
    let confidence: Double
    let riskLevel: String
    let confirmationRequired: Bool
    let status: String
    let safeNextStep: String
    let recipients: [String]
    let channel: String
    let subject: String
    let body: String
    let draftText: String
    let residualConstraints: [String]

    enum CodingKeys: String, CodingKey {
        case prompt
        case ok
        case actionID = "action_id"
        case title
        case domain
        case confidence
        case riskLevel = "risk_level"
        case confirmationRequired = "confirmation_required"
        case status
        case safeNextStep = "safe_next_step"
        case recipients
        case channel
        case subject
        case body
        case draftText = "draft_text"
        case residualConstraints = "residual_constraints"
    }
}

struct ActionCapsule: Codable, Identifiable {
    var id: String { capsuleID }

    let prompt: String
    let capsuleID: String
    let actionID: String
    let title: String
    let domain: String
    let riskLevel: String
    let authorizationLevel: String
    let confirmationRequired: Bool
    let autoSubmitAllowed: Bool
    let status: String
    let summary: String
    let slots: [String: String]
    let draftText: String
    let bridgeKind: String
    let bridgeURL: String
    let bridgeLabel: String
    let bridgeOptions: [ActionBridgeOption]
    let bridgeInstructions: String
    let verifierRequirements: [String]
    let autoSubmitBlockers: [String]
    let residualConstraints: [String]
    let orderSpec: OrderSpec?

    enum CodingKeys: String, CodingKey {
        case prompt
        case capsuleID = "capsule_id"
        case actionID = "action_id"
        case title
        case domain
        case riskLevel = "risk_level"
        case authorizationLevel = "authorization_level"
        case confirmationRequired = "confirmation_required"
        case autoSubmitAllowed = "auto_submit_allowed"
        case status
        case summary
        case slots
        case draftText = "draft_text"
        case bridgeKind = "bridge_kind"
        case bridgeURL = "bridge_url"
        case bridgeLabel = "bridge_label"
        case bridgeOptions = "bridge_options"
        case bridgeInstructions = "bridge_instructions"
        case verifierRequirements = "verifier_requirements"
        case autoSubmitBlockers = "auto_submit_blockers"
        case residualConstraints = "residual_constraints"
        case orderSpec = "order_spec"
    }
}

struct OrderSpec: Codable {
    let kind: String
    let service: OrderSpecField
    let restaurant: OrderSpecField
    let item: OrderSpecField
    let size: OrderSpecField
    let toppings: OrderSpecField
    let addOns: OrderSpecField
    let tip: OrderSpecField
    let clarificationBlockers: [String]

    enum CodingKeys: String, CodingKey {
        case kind
        case service
        case restaurant
        case item
        case size
        case toppings
        case addOns = "add_ons"
        case tip
        case clarificationBlockers = "clarification_blockers"
    }
}

struct OrderSpecField: Codable {
    let values: [String]
    let confidence: Double
    let criticality: String
    let source: String
    let needsClarification: Bool

    enum CodingKeys: String, CodingKey {
        case values
        case confidence
        case criticality
        case source
        case needsClarification = "needs_clarification"
    }
}

struct ActionBridgeOption: Codable, Identifiable {
    var id: String { optionID }

    let optionID: String
    let label: String
    let kind: String
    let url: String
    let instructions: String

    enum CodingKeys: String, CodingKey {
        case optionID = "option_id"
        case label
        case kind
        case url
        case instructions
    }
}

struct BrowserState: Codable {
    let currentURL: String?
    let pageKind: String?
    let searchEngine: String?
    let searchQuery: String?
    let subjectTitle: String?
    let researchSubjectTitle: String?
    let subjectSummary: String?
    let resultCards: [BrowserResultCard]?

    enum CodingKeys: String, CodingKey {
        case currentURL = "current_url"
        case pageKind = "page_kind"
        case searchEngine = "search_engine"
        case searchQuery = "search_query"
        case subjectTitle = "subject_title"
        case researchSubjectTitle = "research_subject_title"
        case subjectSummary = "subject_summary"
        case resultCards = "result_cards"
    }
}

struct BrowserResultCard: Codable, Identifiable {
    var id: String { url.isEmpty ? "\(index)-\(title)" : url }

    let index: Int?
    let title: String
    let url: String
    let summary: String?
    let score: Double?
}

struct MemlaScoutEnvelope: Codable {
    let ok: Bool
    let mode: String
    let result: ScoutResult
    let totalDurationSeconds: Double

    enum CodingKeys: String, CodingKey {
        case ok
        case mode
        case result
        case totalDurationSeconds = "total_duration_seconds"
    }
}

struct ScoutResult: Codable {
    let prompt: String
    let scoutKind: String
    let source: String
    let ok: Bool
    let query: String
    let goal: String
    let topResults: [ScoutCard]
    let bestMatch: ScoutCard?
    let summary: String

    enum CodingKeys: String, CodingKey {
        case prompt
        case scoutKind = "scout_kind"
        case source
        case ok
        case query
        case goal
        case topResults = "top_results"
        case bestMatch = "best_match"
        case summary
    }
}

struct ScoutCard: Codable, Identifiable {
    var id: String { url.isEmpty ? title : url }

    let title: String
    let url: String
    let summary: String?
    let stars: String?
    let language: String?
    let score: Double?
}

struct MemlaRunEnvelope: Codable {
    let ok: Bool
    let mode: String
    let prompt: String
    let plan: MemlaPlan
    let execution: MemlaExecution?
    let totalDurationSeconds: Double

    enum CodingKeys: String, CodingKey {
        case ok
        case mode
        case prompt
        case plan
        case execution
        case totalDurationSeconds = "total_duration_seconds"
    }
}

struct MemlaPlan: Codable {
    let source: String
    let clarification: String
    let residualConstraints: [String]

    enum CodingKeys: String, CodingKey {
        case source
        case clarification
        case residualConstraints = "residual_constraints"
    }
}

struct MemlaExecution: Codable {
    let ok: Bool
    let records: [MemlaExecutionRecord]
    let browserState: BrowserState?

    enum CodingKeys: String, CodingKey {
        case ok
        case records
        case browserState = "browser_state"
    }
}

struct MemlaExecutionRecord: Codable, Identifiable {
    var id: String { "\(kind)-\(target)-\(message)" }

    let kind: String
    let target: String
    let status: String
    let message: String
}
