import Foundation

struct MemlaActivityItem: Identifiable {
    let id = UUID()
    let title: String
    let detail: String
    let timestamp: Date
}

struct MemlaChatMessage: Identifiable {
    let id = UUID()
    let speaker: String
    let title: String
    let detail: String
    let timestamp: Date
    let isUser: Bool
}

@MainActor
final class MemlaViewModel: ObservableObject {
    @Published var baseURL: String {
        didSet {
            UserDefaults.standard.set(baseURL, forKey: "memlaBaseURL")
        }
    }
    @Published var scoutPrompt: String = "find the top 10 github repos for local llms and tell me which best fits weak hardware"
    @Published var webPrompt: String = "what's happening in the news about AI agents today?"
    @Published var followupPrompt: String = "find a youtube video about it then open the first one and summarize it"
    @Published var actionPrompt: String = "ask my sister what she wants from DoorDash"
    @Published var missionPrompt: String = "get pizza from Tony's with pepperoni and give the dasher a $6 tip on DoorDash"
    @Published var healthStatus: String = "Unknown"
    @Published var currentState: BrowserState?
    @Published var memorySummary: MemorySummary?
    @Published var actionSummary: ActionSummary?
    @Published var missionSummary: MissionSummary?
    @Published var missions: [MemlaMission] = []
    @Published var activeMission: MemlaMission?
    @Published var actionDraft: ActionDraft?
    @Published var actionCapsule: ActionCapsule?
    @Published var scoutResult: ScoutResult?
    @Published var webResult: MemlaRunEnvelope?
    @Published var followupResult: MemlaRunEnvelope?
    @Published var chatItems: [MemlaChatMessage] = []
    @Published var activityItems: [MemlaActivityItem] = []
    @Published var errorMessage: String = ""
    @Published var isLoading: Bool = false

    init() {
        self.baseURL = UserDefaults.standard.string(forKey: "memlaBaseURL") ?? "http://192.168.1.10:8080"
    }

    func refreshHealth() async {
        await runTask { [self] in
            let response = try await MemlaClient.shared.health(baseURL: self.baseURL)
            self.healthStatus = response.ok ? "Connected" : "Unavailable"
            self.appendActivity(title: "Health Check", detail: self.healthStatus)
        }
    }

    func refreshState() async {
        await runTask { [self] in
            let response = try await MemlaClient.shared.state(baseURL: self.baseURL)
            self.currentState = response.state
            self.appendActivity(title: "State Refresh", detail: self.currentState?.pageKind ?? "unknown")
        }
    }

    func refreshMemory() async {
        await runTask { [self] in
            let response = try await MemlaClient.shared.memory(baseURL: self.baseURL)
            self.memorySummary = response.summary
            let autonomy = response.summary.autonomyCount ?? 0
            self.appendActivity(title: "Memory Refresh", detail: "rule \(response.summary.ruleCount), semantic \(response.summary.semanticCount), episodic \(response.summary.episodicCount), autonomy \(autonomy)")
        }
    }

    func refreshActions() async {
        await runTask { [self] in
            let response = try await MemlaClient.shared.actions(baseURL: self.baseURL)
            self.actionSummary = response.summary
            self.appendActivity(title: "Action Ontology", detail: "\(response.summary.actionCount) actions, \(response.summary.confirmationRequiredCount) confirmation-gated")
        }
    }

    func refreshMissions() async {
        await runTask { [self] in
            let response = try await MemlaClient.shared.missions(baseURL: self.baseURL)
            self.missionSummary = response.summary
            self.missions = response.missions
            if self.activeMission == nil {
                self.activeMission = response.missions.first
            }
            self.appendActivity(title: "Mission Queue", detail: "\(response.summary.missionCount) missions")
        }
    }

    func startMission() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Mission", detail: self.missionPrompt, isUser: true)
            let response = try await MemlaClient.shared.createMission(prompt: self.missionPrompt, baseURL: self.baseURL)
            self.activeMission = response.mission
            let missionsEnvelope = try await MemlaClient.shared.missions(baseURL: self.baseURL)
            self.missionSummary = missionsEnvelope.summary
            self.missions = missionsEnvelope.missions
            self.appendChat(speaker: "Memla", title: response.mission.checkpoint.title, detail: response.mission.checkpoint.detail, isUser: false)
            self.appendActivity(title: "Mission Started", detail: "\(response.mission.actionID) - \(response.mission.status)")
        }
    }

    func decideMission(_ decision: String, note: String = "") async {
        guard let mission = activeMission else {
            return
        }
        await runTask { [self] in
            let response = try await MemlaClient.shared.decideMission(
                missionID: mission.missionID,
                decision: decision,
                note: note,
                baseURL: self.baseURL
            )
            self.activeMission = response.mission
            let missionsEnvelope = try await MemlaClient.shared.missions(baseURL: self.baseURL)
            self.missionSummary = missionsEnvelope.summary
            self.missions = missionsEnvelope.missions
            self.appendChat(speaker: "You", title: "Mission Decision", detail: decision, isUser: true)
            self.appendChat(speaker: "Memla", title: response.mission.checkpoint.title, detail: response.mission.checkpoint.detail, isUser: false)
            self.appendActivity(title: "Mission Decision", detail: "\(decision) -> \(response.mission.status)")
        }
    }

    func draftAction() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Action Draft", detail: self.actionPrompt, isUser: true)
            let response = try await MemlaClient.shared.actionDraft(prompt: self.actionPrompt, baseURL: self.baseURL)
            self.actionDraft = response.draft
            try await self.refreshRuntimeSnapshots()
            let detail = response.draft.draftText.isEmpty ? response.draft.residualConstraints.joined(separator: ", ") : response.draft.draftText
            self.appendChat(speaker: "Memla", title: response.draft.title, detail: detail, isUser: false)
            self.appendActivity(title: "Action Draft", detail: "\(response.draft.actionID) - \(response.draft.safeNextStep)")
        }
    }

    func buildActionCapsule() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Action Capsule", detail: self.actionPrompt, isUser: true)
            let response = try await MemlaClient.shared.actionCapsule(prompt: self.actionPrompt, baseURL: self.baseURL)
            self.actionCapsule = response.capsule
            try await self.refreshRuntimeSnapshots()
            self.appendChat(speaker: "Memla", title: response.capsule.title, detail: response.capsule.summary, isUser: false)
            self.appendActivity(title: "Action Capsule", detail: "\(response.capsule.actionID) - \(response.capsule.authorizationLevel)")
        }
    }

    func runScout() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Scout", detail: self.scoutPrompt, isUser: true)
            let envelope = try await MemlaClient.shared.scout(prompt: self.scoutPrompt, baseURL: self.baseURL)
            self.scoutResult = envelope.result
            self.webResult = nil
            self.followupResult = nil
            try await self.refreshRuntimeSnapshots()
            self.appendChat(
                speaker: "Memla",
                title: self.scoutTitle(for: envelope.result),
                detail: envelope.result.summary,
                isUser: false
            )
            self.appendActivity(title: "Scout", detail: envelope.result.summary)
        }
    }

    func runWeb() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Web", detail: self.webPrompt, isUser: true)
            let envelope = try await MemlaClient.shared.run(prompt: self.webPrompt, baseURL: self.baseURL, heuristicOnly: false)
            self.webResult = envelope
            try await self.refreshRuntimeSnapshots()
            let detail = self.summaryLine(for: envelope)
            self.appendChat(speaker: "Memla", title: "Web Answer", detail: detail, isUser: false)
            self.appendActivity(title: "Web", detail: detail)
        }
    }

    func runFollowup() async {
        await runTask { [self] in
            self.appendChat(speaker: "You", title: "Follow-up", detail: self.followupPrompt, isUser: true)
            let envelope = try await MemlaClient.shared.followup(prompt: self.followupPrompt, baseURL: self.baseURL, heuristicOnly: false)
            self.followupResult = envelope
            try await self.refreshRuntimeSnapshots()
            let detail = self.summaryLine(for: envelope)
            self.appendChat(speaker: "Memla", title: "Follow-up Result", detail: detail, isUser: false)
            self.appendActivity(title: "Follow-up", detail: detail)
        }
    }

    func runLocalLLMDemo() async {
        await runTask { [self] in
            let demoScoutPrompt = "find the top 10 github repos for local llms and tell me which best fits weak hardware"
            self.scoutPrompt = demoScoutPrompt
            self.appendChat(speaker: "You", title: "One-Tap Demo", detail: demoScoutPrompt, isUser: true)

            let scoutEnvelope = try await MemlaClient.shared.scout(prompt: demoScoutPrompt, baseURL: self.baseURL)
            self.scoutResult = scoutEnvelope.result
            self.followupResult = nil
            try await self.refreshRuntimeSnapshots()
            self.appendChat(
                speaker: "Memla",
                title: self.scoutTitle(for: scoutEnvelope.result),
                detail: scoutEnvelope.result.summary,
                isUser: false
            )

            let winner = self.demoWinnerTitle(from: scoutEnvelope.result)

            let youtubePrompt = "find a youtube video about \(winner) then open the first one and summarize it"
            self.followupPrompt = youtubePrompt
            self.appendChat(speaker: "You", title: "YouTube Follow-up", detail: youtubePrompt, isUser: true)
            let youtubeEnvelope = try await MemlaClient.shared.followup(prompt: youtubePrompt, baseURL: self.baseURL, heuristicOnly: false)
            self.followupResult = youtubeEnvelope
            try await self.refreshRuntimeSnapshots()
            self.appendChat(speaker: "Memla", title: "YouTube Result", detail: self.summaryLine(for: youtubeEnvelope), isUser: false)

            let redditPrompt = "find a reddit post about \(winner) then open the first one and explain it"
            self.followupPrompt = redditPrompt
            self.appendChat(speaker: "You", title: "Reddit Follow-up", detail: redditPrompt, isUser: true)
            let redditEnvelope = try await MemlaClient.shared.followup(prompt: redditPrompt, baseURL: self.baseURL, heuristicOnly: false)
            self.followupResult = redditEnvelope
            try await self.refreshRuntimeSnapshots()
            self.appendChat(speaker: "Memla", title: "Reddit Result", detail: self.summaryLine(for: redditEnvelope), isUser: false)

            let synthesisPrompt = "tell me which source best explains what \(winner) is for"
            self.followupPrompt = synthesisPrompt
            self.appendChat(speaker: "You", title: "Final Compare", detail: synthesisPrompt, isUser: true)
            let synthesisEnvelope = try await MemlaClient.shared.followup(prompt: synthesisPrompt, baseURL: self.baseURL, heuristicOnly: false)
            self.followupResult = synthesisEnvelope
            try await self.refreshRuntimeSnapshots()
            self.appendChat(speaker: "Memla", title: "Final Answer", detail: self.summaryLine(for: synthesisEnvelope), isUser: false)
            self.appendActivity(title: "One-Tap Demo", detail: "Completed local LLM scout, YouTube, Reddit, and final comparison.")
        }
    }

    func applyScoutPreset(_ prompt: String) {
        scoutPrompt = prompt
    }

    func applyWebPreset(_ prompt: String) {
        webPrompt = prompt
    }

    func applyFollowupPreset(_ prompt: String) {
        followupPrompt = prompt
    }

    func useWinnerForYouTubeFollowup() {
        if let title = scoutResult?.bestMatch?.title, !title.isEmpty {
            followupPrompt = "find a youtube video about \(title) then open the first one and summarize it"
            return
        }
        followupPrompt = "find a youtube video about it then open the first one and summarize it"
    }

    func useWinnerForRedditFollowup() {
        if let title = scoutResult?.bestMatch?.title, !title.isEmpty {
            followupPrompt = "find a reddit post about \(title) then open the first one and explain it"
            return
        }
        followupPrompt = "find a reddit post about it then open the first one and explain it"
    }

    func clearActivity() {
        activityItems.removeAll()
    }

    func clearChat() {
        chatItems.removeAll()
    }

    private func runTask(_ operation: @escaping () async throws -> Void) async {
        isLoading = true
        errorMessage = ""
        defer { isLoading = false }
        do {
            try await operation()
        } catch {
            errorMessage = error.localizedDescription
            appendChat(speaker: "Memla", title: "Error", detail: error.localizedDescription, isUser: false)
        }
    }

    private func refreshRuntimeSnapshots() async throws {
        currentState = try await MemlaClient.shared.state(baseURL: baseURL).state
        memorySummary = try await MemlaClient.shared.memory(baseURL: baseURL).summary
        actionSummary = try await MemlaClient.shared.actions(baseURL: baseURL).summary
        let missionEnvelope = try await MemlaClient.shared.missions(baseURL: baseURL)
        missionSummary = missionEnvelope.summary
        missions = missionEnvelope.missions
    }

    private func scoutTitle(for result: ScoutResult) -> String {
        if let title = result.bestMatch?.title, !title.isEmpty {
            return "Best Match: \(title)"
        }
        return "Scout Result"
    }

    private func demoWinnerTitle(from result: ScoutResult) -> String {
        if let title = result.bestMatch?.title, !title.isEmpty {
            return title
        }
        if let title = result.topResults.first?.title, !title.isEmpty {
            return title
        }
        if !result.query.isEmpty {
            return result.query
        }
        return "the winning repo"
    }

    func summaryLine(for envelope: MemlaRunEnvelope) -> String {
        if let browserState = envelope.execution?.browserState {
            let subjectSummary = browserState.subjectSummary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if !subjectSummary.isEmpty {
                return subjectSummary
            }
        }
        if let records = envelope.execution?.records, !records.isEmpty {
            let messages = records.map { $0.message.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            if !messages.isEmpty {
                return messages.joined(separator: "\n")
            }
        }
        if !envelope.plan.clarification.isEmpty {
            return envelope.plan.clarification
        }
        if !envelope.plan.residualConstraints.isEmpty {
            return envelope.plan.residualConstraints.joined(separator: ", ")
        }
        return envelope.ok ? "Done." : "Memla could not complete that follow-up yet."
    }

    private func appendChat(speaker: String, title: String, detail: String, isUser: Bool) {
        let cleanTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanDetail = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanTitle.isEmpty || !cleanDetail.isEmpty else {
            return
        }
        chatItems.append(
            MemlaChatMessage(
                speaker: speaker,
                title: cleanTitle.isEmpty ? speaker : cleanTitle,
                detail: cleanDetail,
                timestamp: Date(),
                isUser: isUser
            )
        )
        if chatItems.count > 30 {
            chatItems = Array(chatItems.suffix(30))
        }
    }

    private func appendActivity(title: String, detail: String) {
        let cleanTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanDetail = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanTitle.isEmpty || !cleanDetail.isEmpty else {
            return
        }
        activityItems.insert(
            MemlaActivityItem(
                title: cleanTitle.isEmpty ? "Memla" : cleanTitle,
                detail: cleanDetail,
                timestamp: Date()
            ),
            at: 0
        )
        if activityItems.count > 12 {
            activityItems = Array(activityItems.prefix(12))
        }
    }
}
