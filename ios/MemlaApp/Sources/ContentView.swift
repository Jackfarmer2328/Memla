import Foundation
import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var viewModel: MemlaViewModel
    @State private var browserRoute: MemlaBrowserRoute?
    private let scoutPresets = [
        "find the top 10 github repos for local llms and tell me which best fits weak hardware",
        "find the top 10 github repos for browser agents and tell me which looks strongest",
        "find the top 10 github repos for local coding agents and tell me which is most active",
    ]
    private let webPresets = [
        "what's happening in the news about AI agents today?",
        "who built the Saturn V rocket engines?",
        "what changed in the latest OpenAI API release?",
    ]
    private let followupPresets = [
        "find a youtube video about it then open the first one and summarize it",
        "find a reddit post about it then open the first one and explain it",
        "tell me which source best explains what this project is for",
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    connectionCard
                    missionControlCard
                    missionQueueCard
                    chatCard
                    webCard
                    scoutCard
                    stateCard
                    memoryCard
                    actionOntologyCard
                    followupCard
                    activityCard
                }
                .padding(20)
            }
            .navigationTitle("Memla")
            .task {
                await viewModel.refreshHealth()
                await viewModel.refreshState()
                await viewModel.refreshMemory()
                await viewModel.refreshActions()
                await viewModel.refreshMissions()
            }
            .sheet(item: $browserRoute) { route in
                MemlaBrowserView(route: route)
            }
        }
    }

    private var connectionCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Connection")
                .font(.headline)
            TextField("http://192.168.1.10:8080", text: $viewModel.baseURL)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .textFieldStyle(.roundedBorder)
            Text("On iPhone, use your PC's local Wi-Fi IP like http://192.168.1.23:8080. Don't use 0.0.0.0; that's only for starting the server on your PC.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Text("Status: \(viewModel.healthStatus)")
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Use Default") {
                    viewModel.baseURL = "http://192.168.1.10:8080"
                }
                Button("Refresh") {
                    Task {
                        await viewModel.refreshHealth()
                        await viewModel.refreshState()
                        await viewModel.refreshMemory()
                        await viewModel.refreshActions()
                        await viewModel.refreshMissions()
                    }
                }
            }
            if !viewModel.errorMessage.isEmpty {
                Text(viewModel.errorMessage)
                    .foregroundStyle(.red)
                    .font(.footnote)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var missionControlCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Mission Control")
                .font(.headline)
            Text("Tap once and Memla will scout repos, follow the winner to YouTube and Reddit, then bring back a final comparison.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Button(viewModel.isLoading ? "Running Mission..." : "Run Local LLM Demo") {
                Task { await viewModel.runLocalLLMDemo() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)
            Text("Voice note: iPhone keyboard dictation already works in the prompt fields. Siri can use the existing \"Scout with Memla\" App Intent after install/Shortcuts validation.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(
            LinearGradient(
                colors: [
                    Color.blue.opacity(0.18),
                    Color.teal.opacity(0.10),
                    Color(.secondarySystemBackground),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
    }

    private var missionQueueCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Mission Queue")
                        .font(.headline)
                    Text("Start a local mission, then approve/open/cancel checkpoints.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Refresh") {
                    Task { await viewModel.refreshMissions() }
                }
                .font(.caption)
            }

            TextField("What should Memla do?", text: $viewModel.missionPrompt, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)

            Button(viewModel.isLoading ? "Starting..." : "Start Mission") {
                Task { await viewModel.startMission() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)

            if let mission = viewModel.activeMission {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(mission.title)
                            .font(.caption.weight(.semibold))
                        Spacer()
                        Text(readableRequirement(mission.status))
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(mission.status == "cancelled" ? .red : .orange)
                    }
                    Text(mission.prompt)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)

                    VStack(alignment: .leading, spacing: 5) {
                        Text(mission.checkpoint.title)
                            .font(.subheadline.weight(.semibold))
                        Text(mission.checkpoint.detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(4)
                        HStack(spacing: 8) {
                            chip(text: readableRequirement(mission.checkpoint.kind))
                            chip(text: readableRequirement(mission.checkpoint.safetyLevel))
                        }
                    }
                    .padding(10)
                    .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

                    HStack {
                        if mission.checkpoint.decisions.contains("approve") {
                            Button("Approve") {
                                Task { await viewModel.decideMission("approve") }
                            }
                            .buttonStyle(.bordered)
                            .disabled(viewModel.isLoading)
                        }
                        if mission.checkpoint.decisions.contains("open"), mission.checkpoint.bridgeOption != nil {
                            Button("Open") {
                                openMissionBridge(mission)
                                Task { await viewModel.decideMission("open") }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(viewModel.isLoading)
                        }
                        if mission.checkpoint.decisions.contains("cancel") {
                            Button("Cancel") {
                                Task { await viewModel.decideMission("cancel") }
                            }
                            .buttonStyle(.bordered)
                            .tint(.red)
                            .disabled(viewModel.isLoading)
                        }
                    }

                    if mission.checkpoint.decisions.contains("modify") {
                        Button("Mark Needs Changes") {
                            Task { await viewModel.decideMission("modify", note: "User asked to modify this mission before continuing.") }
                        }
                        .buttonStyle(.bordered)
                        .disabled(viewModel.isLoading)
                    }
                }
                .padding(10)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            } else if let summary = viewModel.missionSummary {
                Text("\(summary.missionCount) missions queued.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("No mission loaded yet.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var chatCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Conversation")
                    .font(.headline)
                Spacer()
                if !viewModel.chatItems.isEmpty {
                    Button("Clear") {
                        viewModel.clearChat()
                    }
                    .font(.caption)
                }
            }

            if viewModel.chatItems.isEmpty {
                Text("Run the demo or a scout and Memla will write the agent trace here.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                VStack(spacing: 10) {
                    ForEach(viewModel.chatItems) { message in
                        chatBubble(message)
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var scoutCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Scout")
                .font(.headline)
            TextField("What should Memla scout?", text: $viewModel.scoutPrompt, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(3...6)
            presetChips(items: scoutPresets) { preset in
                viewModel.applyScoutPreset(preset)
            }
            Button(viewModel.isLoading ? "Running..." : "Run Scout") {
                Task { await viewModel.runScout() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)

            if let scout = viewModel.scoutResult {
                Text(scout.summary)
                    .font(.subheadline)
                if let best = scout.bestMatch {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Best Match")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(best.title)
                            .font(.headline)
                        HStack(spacing: 8) {
                            if let score = best.score {
                                chip(text: "score \(String(format: "%.2f", score))")
                            }
                            if let stars = best.stars, !stars.isEmpty {
                                chip(text: stars)
                            }
                            if let language = best.language, !language.isEmpty {
                                chip(text: language)
                            }
                        }
                        if let summary = best.summary, !summary.isEmpty {
                            Text(summary)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        Text(best.url)
                            .font(.caption2)
                            .foregroundStyle(.blue)
                    }
                    .padding()
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                if !scout.topResults.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Top Results")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        ForEach(scout.topResults.prefix(5)) { item in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(alignment: .top) {
                                    Text(item.title)
                                        .font(.subheadline.weight(.medium))
                                    Spacer(minLength: 8)
                                    if let score = item.score {
                                        Text(String(format: "%.2f", score))
                                            .font(.caption2.weight(.semibold))
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                HStack(spacing: 8) {
                                    if let stars = item.stars, !stars.isEmpty {
                                        chip(text: stars)
                                    }
                                    if let language = item.language, !language.isEmpty {
                                        chip(text: language)
                                    }
                                }
                                if let summary = item.summary, !summary.isEmpty {
                                    Text(summary)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var webCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Memla's Web")
                        .font(.headline)
                    Text("Ask a web question and let Memla search, read, and bring back the answer.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let result = viewModel.webResult?.execution?.browserState?.currentURL,
                   !result.isEmpty {
                    Button("Open Result") {
                        openWebResult(result)
                    }
                    .font(.caption)
                }
            }

            TextField("What should Memla look up?", text: $viewModel.webPrompt, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...5)

            presetChips(items: webPresets) { preset in
                viewModel.applyWebPreset(preset)
            }

            Button(viewModel.isLoading ? "Searching..." : "Ask The Web") {
                Task { await viewModel.runWeb() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.isLoading)

            if let result = viewModel.webResult {
                Text(viewModel.summaryLine(for: result))
                    .font(.subheadline)

                HStack(spacing: 8) {
                    chip(text: "plan \(result.plan.source)")
                    if let pageKind = result.execution?.browserState?.pageKind, !pageKind.isEmpty {
                        chip(text: pageKind.replacingOccurrences(of: "_", with: " "))
                    }
                }

                if let browserState = result.execution?.browserState {
                    VStack(alignment: .leading, spacing: 4) {
                        if let subject = browserState.subjectTitle ?? browserState.researchSubjectTitle, !subject.isEmpty {
                            Text(subject)
                                .font(.caption.weight(.semibold))
                        }
                        if let subjectSummary = browserState.subjectSummary, !subjectSummary.isEmpty {
                            Text(subjectSummary)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(3)
                        }
                        if let currentURL = browserState.currentURL, !currentURL.isEmpty {
                            Text(currentURL)
                                .font(.caption2)
                                .foregroundStyle(.blue)
                                .lineLimit(2)
                        }
                    }
                    .padding(10)
                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

                    if let resultCards = browserState.resultCards, !resultCards.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Sources")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            ForEach(Array(resultCards.prefix(3))) { card in
                                VStack(alignment: .leading, spacing: 3) {
                                    HStack(alignment: .top) {
                                        Text(card.title)
                                            .font(.caption.weight(.semibold))
                                            .lineLimit(2)
                                        Spacer(minLength: 8)
                                        if !card.url.isEmpty {
                                            Button("Open") {
                                                openWebResult(card.url)
                                            }
                                            .font(.caption2.weight(.semibold))
                                        }
                                        if let score = card.score {
                                            Text(String(format: "%.2f", score))
                                                .font(.caption2.weight(.semibold))
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    if let summary = card.summary, !summary.isEmpty {
                                        Text(summary)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                    if !card.url.isEmpty {
                                        Text(card.url)
                                            .font(.caption2)
                                            .foregroundStyle(.blue)
                                            .lineLimit(1)
                                    }
                                }
                                .padding(10)
                                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            Text("Try follow-ups like \"open the second source\" or \"compare the first and second source.\"")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if let execution = result.execution, !execution.records.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Web Trace")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        ForEach(execution.records.prefix(6)) { record in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(record.kind)
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.secondary)
                                Text(record.message)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var stateCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Current State")
                .font(.headline)
            if let state = viewModel.currentState {
                LabeledContent("Page", value: state.pageKind ?? "unknown")
                LabeledContent("Search", value: state.searchQuery ?? "none")
                LabeledContent("Subject", value: state.subjectTitle ?? state.researchSubjectTitle ?? "none")
                if let currentURL = state.currentURL, !currentURL.isEmpty {
                    Text(currentURL)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Text("No browser state yet.")
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var memoryCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Memory")
                        .font(.headline)
                    Text("Governed operational memory")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Refresh") {
                    Task { await viewModel.refreshMemory() }
                }
                .font(.caption)
            }

            if let memory = viewModel.memorySummary {
                HStack(spacing: 10) {
                    memoryMetric(title: "Episodic", value: "\(memory.episodicCount)")
                    memoryMetric(title: "Semantic", value: "\(memory.semanticCount)")
                    memoryMetric(title: "Rule", value: "\(memory.ruleCount)")
                }
                HStack(spacing: 10) {
                    memoryMetric(title: "Autonomy", value: "\(memory.autonomyCount ?? 0)")
                    memoryMetric(title: "Actions", value: "\(memory.actionCount ?? 0)")
                    memoryMetric(title: "Language", value: "\(memory.languageCount ?? 0)")
                }
                HStack(spacing: 10) {
                    memoryMetric(title: "Active", value: "\(memory.activeCount)")
                    memoryMetric(title: "Stale", value: "\(memory.staleCount)")
                    memoryMetric(title: "Invalid", value: "\(memory.invalidCount)")
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Trust")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(String(format: "%.2f", memory.avgTrust))
                            .font(.caption.weight(.semibold))
                    }
                    ProgressView(value: min(max(memory.avgTrust, 0.0), 1.0))
                }
                Text("Memla writes down successful structure, tests reuse, and promotes repeated wins into rules.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("No memory summary loaded yet. Refresh after a scout or follow-up to see the lifecycle state.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var actionOntologyCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Action Ontology")
                        .font(.headline)
                    Text("Safe app-action layer")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Refresh") {
                    Task { await viewModel.refreshActions() }
                }
                .font(.caption)
            }

            if let actions = viewModel.actionSummary {
                HStack(spacing: 10) {
                    memoryMetric(title: "Actions", value: "\(actions.actionCount)")
                    memoryMetric(title: "Ready", value: "\(actions.implementedCount)")
                    memoryMetric(title: "Confirm", value: "\(actions.confirmationRequiredCount)")
                }
                Text(actions.domains.joined(separator: "  "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                ForEach(actions.capabilities.prefix(4)) { capability in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(capability.title)
                                .font(.caption.weight(.semibold))
                            Text("\(capability.domain) - \(capability.status)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(capability.confirmationRequired ? "confirm" : "auto")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(capability.confirmationRequired ? .orange : .green)
                    }
                }
                Text("Money, rides, and messages stay confirmation-gated while Memla learns the action shape.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Divider()
                Text("Draft Action")
                    .font(.caption.weight(.semibold))
                TextField("Ask a contact or draft an email", text: $viewModel.actionPrompt, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...4)
                HStack {
                    Button(viewModel.isLoading ? "Drafting..." : "Draft Safely") {
                        Task { await viewModel.draftAction() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel.isLoading)
                    Button(viewModel.isLoading ? "Building..." : "Build Capsule") {
                        Task { await viewModel.buildActionCapsule() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(viewModel.isLoading)
                }
                if let draft = viewModel.actionDraft {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(draft.title)
                            .font(.caption.weight(.semibold))
                        Text("\(draft.domain) - \(draft.status) - \(draft.safeNextStep)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        if !draft.recipients.isEmpty {
                            Text("To: \(draft.recipients.joined(separator: ", "))")
                                .font(.caption)
                        }
                        if !draft.subject.isEmpty {
                            Text("Subject: \(draft.subject)")
                                .font(.caption)
                        }
                        if !draft.draftText.isEmpty {
                            Text(draft.draftText)
                                .font(.subheadline)
                                .textSelection(.enabled)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        if draft.domain == "messaging", !draft.body.isEmpty {
                            Button("Open Message Draft") {
                                openMessageDraft(body: draft.body)
                            }
                            .buttonStyle(.bordered)
                            Text("You choose the recipient and press Send. Memla will not send this automatically.")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        if !draft.residualConstraints.isEmpty {
                            Text(draft.residualConstraints.joined(separator: ", "))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                if let capsule = viewModel.actionCapsule {
                    VStack(alignment: .leading, spacing: 8) {
                        Divider()
                        Text("Action Capsule")
                            .font(.caption.weight(.semibold))
                        Text("\(capsule.status) - \(capsule.authorizationLevel)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text(capsule.summary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        if !capsule.slots.isEmpty {
                            VStack(alignment: .leading, spacing: 4) {
                                ForEach(capsule.slots.keys.sorted(), id: \.self) { key in
                                    if let value = capsule.slots[key], !value.isEmpty {
                                        LabeledContent(key.replacingOccurrences(of: "_", with: " ").capitalized, value: value)
                                            .font(.caption)
                                    }
                                }
                            }
                        }
                        if !capsule.draftText.isEmpty {
                            Text(capsule.draftText)
                                .font(.caption)
                                .textSelection(.enabled)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        HStack {
                            chip(text: capsule.autoSubmitAllowed ? "auto-submit eligible" : "manual confirm")
                            chip(text: capsule.riskLevel)
                        }
                        if !capsule.bridgeOptions.isEmpty {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack {
                                    ForEach(capsule.bridgeOptions) { option in
                                        Button(option.label) {
                                            openBridgeOption(option)
                                        }
                                        .buttonStyle(.bordered)
                                    }
                                }
                            }
                        } else if !capsule.bridgeURL.isEmpty {
                            Button(capsule.bridgeLabel.isEmpty ? "Open Bridge" : capsule.bridgeLabel) {
                                openURLString(capsule.bridgeURL)
                            }
                            .buttonStyle(.bordered)
                        }
                        if !capsule.bridgeInstructions.isEmpty {
                            Text(capsule.bridgeInstructions)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        if !capsule.autoSubmitBlockers.isEmpty {
                            Text("Blocked from auto-submit: \(capsule.autoSubmitBlockers.joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            } else {
                Text("No action ontology summary loaded yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var followupCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Follow-up")
                .font(.headline)
            TextField("What should Memla do next?", text: $viewModel.followupPrompt, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...5)
            presetChips(items: followupPresets) { preset in
                viewModel.applyFollowupPreset(preset)
            }
            if viewModel.scoutResult?.bestMatch != nil {
                HStack {
                    Button("Use Winner -> YouTube") {
                        viewModel.useWinnerForYouTubeFollowup()
                    }
                    .buttonStyle(.bordered)
                    Button("Use Winner -> Reddit") {
                        viewModel.useWinnerForRedditFollowup()
                    }
                    .buttonStyle(.bordered)
                }
            }
            Button(viewModel.isLoading ? "Running..." : "Run Follow-up") {
                Task { await viewModel.runFollowup() }
            }
            .buttonStyle(.bordered)
            .disabled(viewModel.isLoading)

            if let result = viewModel.followupResult {
                Text("Plan Source: \(result.plan.source)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let execution = result.execution {
                    ForEach(execution.records) { record in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(record.kind)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(record.message)
                                .font(.subheadline)
                        }
                    }
                } else if !result.plan.clarification.isEmpty {
                    Text(result.plan.clarification)
                        .font(.subheadline)
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private var activityCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Activity")
                    .font(.headline)
                Spacer()
                if !viewModel.activityItems.isEmpty {
                    Button("Clear") {
                        viewModel.clearActivity()
                    }
                    .font(.caption)
                }
            }
            if viewModel.activityItems.isEmpty {
                Text("Your local scout and follow-up actions will show up here.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(viewModel.activityItems) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(item.title)
                                .font(.subheadline.weight(.medium))
                            Spacer()
                            Text(item.timestamp.formatted(date: .omitted, time: .shortened))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Text(item.detail)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    @ViewBuilder
    private func presetChips(items: [String], action: @escaping (String) -> Void) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(items, id: \.self) { item in
                    Button {
                        action(item)
                    } label: {
                        Text(item)
                            .lineLimit(1)
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)
                }
            }
        }
    }

    private func chip(text: String) -> some View {
        Text(text)
            .font(.caption2)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color(.tertiarySystemBackground), in: Capsule())
    }

    private func memoryMetric(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func chatBubble(_ message: MemlaChatMessage) -> some View {
        HStack(alignment: .top) {
            if message.isUser {
                Spacer(minLength: 42)
            }
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(message.speaker)
                        .font(.caption.weight(.semibold))
                    Spacer(minLength: 8)
                    Text(message.timestamp.formatted(date: .omitted, time: .shortened))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text(message.title)
                    .font(.subheadline.weight(.semibold))
                if !message.detail.isEmpty {
                    Text(message.detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(12)
            .background(
                message.isUser ? Color.accentColor.opacity(0.14) : Color(.secondarySystemBackground),
                in: RoundedRectangle(cornerRadius: 16, style: .continuous)
            )
            if !message.isUser {
                Spacer(minLength: 42)
            }
        }
    }

    private func readableRequirement(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private func openMessageDraft(body: String) {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&+=?")
        let encodedBody = body.addingPercentEncoding(withAllowedCharacters: allowed) ?? body
        guard let url = URL(string: "sms:?&body=\(encodedBody)") else {
            return
        }
        UIApplication.shared.open(url)
    }

    private func openURLString(_ value: String) {
        guard let url = URL(string: value) else {
            return
        }
        UIApplication.shared.open(url)
    }

    private func openBridgeOption(_ option: ActionBridgeOption) {
        guard let url = URL(string: option.url) else {
            return
        }
        if option.kind == "in_app_web" {
            browserRoute = MemlaBrowserRoute(url: url, capsule: viewModel.actionCapsule, option: option)
            return
        }
        UIApplication.shared.open(url)
    }

    private func openMissionBridge(_ mission: MemlaMission) {
        guard let option = mission.checkpoint.bridgeOption,
              let url = URL(string: option.url) else {
            return
        }
        if option.kind == "in_app_web" {
            browserRoute = MemlaBrowserRoute(url: url, capsule: mission.capsule, option: option)
            return
        }
        UIApplication.shared.open(url)
    }

    private func openWebResult(_ value: String) {
        guard let url = URL(string: value) else {
            return
        }
        browserRoute = MemlaBrowserRoute(url: url, capsule: nil, option: nil)
    }
}

#Preview {
    ContentView()
        .environmentObject(MemlaViewModel())
}
