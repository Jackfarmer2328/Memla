import Foundation
import SwiftUI
import UIKit
import WebKit
import Combine

struct MemlaBrowserRoute: Identifiable {
    let id = UUID()
    let url: URL
    let capsule: ActionCapsule?
    let option: ActionBridgeOption?
}

struct WebsiteC2ACandidate: Identifiable {
    let id: String
    let domIndex: Int
    let label: String
    let url: String
    let kind: String
    let role: String
    let score: Double
    let matchedTerms: [String]
    let blocked: Bool
    let tapSafety: String
    let tapReason: String
    let reason: String
    let groupKey: String
    let groupLabel: String
    let groupRequired: Bool
    let tapFingerprint: String
    let isSelected: Bool
    let opensSubflow: Bool

    init(
        id: String,
        domIndex: Int,
        label: String,
        url: String,
        kind: String,
        role: String,
        score: Double,
        matchedTerms: [String],
        blocked: Bool,
        tapSafety: String,
        tapReason: String,
        reason: String,
        groupKey: String = "",
        groupLabel: String = "",
        groupRequired: Bool = false,
        tapFingerprint: String = "",
        isSelected: Bool = false,
        opensSubflow: Bool = false
    ) {
        self.id = id
        self.domIndex = domIndex
        self.label = label
        self.url = url
        self.kind = kind
        self.role = role
        self.score = score
        self.matchedTerms = matchedTerms
        self.blocked = blocked
        self.tapSafety = tapSafety
        self.tapReason = tapReason
        self.reason = reason
        self.groupKey = groupKey
        self.groupLabel = groupLabel
        self.groupRequired = groupRequired
        self.tapFingerprint = tapFingerprint
        self.isSelected = isSelected
        self.opensSubflow = opensSubflow
    }
}

struct WebsiteC2AState {
    let pageKind: String
    let summary: String
    let headings: [String]
    let inputs: [String]
    let buttons: [String]
    let links: [String]
    let candidates: [WebsiteC2ACandidate]
    let safeActions: [String]
    let residuals: [String]
    let authState: String
    let authDomain: String
    let textSnippet: String
    let serviceFacts: [String: String]
    let capsuleVerification: WebsiteCapsuleVerification?
}

struct WebsiteCapsuleVerification {
    let matched: [String]
    let missing: [String]
    let warnings: [String]
    let summary: String
}

struct WebsiteBridgeSuggestion: Identifiable {
    let id: String
    let option: ActionBridgeOption
    let reason: String
}

struct WebsiteGuidedStep {
    let title: String
    let detail: String
    let icon: String
    let tone: String
}

struct WebsiteMirrorFact: Identifiable {
    let id: String
    let title: String
    let value: String
}

final class MemlaBrowserModel: NSObject, ObservableObject, WKNavigationDelegate {
    let webView: WKWebView

    @Published var pageTitle: String = "Loading"
    @Published var currentURL: String = ""
    @Published var isLoading: Bool = false
    @Published var canGoBack: Bool = false
    @Published var canGoForward: Bool = false
    @Published var websiteState: WebsiteC2AState?
    @Published var inspectionStatus: String = ""
    @Published var isInspecting: Bool = false
    @Published var searchActionStatus: String = ""
    @Published var isRunningSearchAction: Bool = false
    @Published var buttonActionStatus: String = ""
    @Published var isRunningButtonAction: Bool = false

    private var shouldAutoInspectAfterNavigation = false
    private var autoInspectCapsule: ActionCapsule?
    private var observationCapsule: ActionCapsule?
    private var pageObservationTimer: Timer?
    private var lastObservedFingerprint: String = ""
    private var isAutoInspectQueued = false
    private var queuedInspectRequested = false
    private var queuedInspectCapsule: ActionCapsule?
    private var inspectSequence = 0
    private var activeInspectToken: Int?
    private var inspectTimeoutWorkItem: DispatchWorkItem?
    private var suppressGroundingUntil: Date = .distantPast
    private var lastDoorDashStorefrontWarmupURL: String = ""
    private var doorDashStorefrontWarmupAttempts = 0

    override init() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        self.webView = WKWebView(frame: .zero, configuration: configuration)
        super.init()
        self.webView.navigationDelegate = self
    }

    deinit {
        pageObservationTimer?.invalidate()
        inspectTimeoutWorkItem?.cancel()
    }

    func load(_ url: URL) {
        if webView.url == nil {
            webView.load(URLRequest(url: url))
        }
        syncState()
    }

    func startGrounding(capsule: ActionCapsule?) {
        observationCapsule = capsule
        guard pageObservationTimer == nil else {
            return
        }
        let timer = Timer(timeInterval: 1.35, repeats: true) { [weak self] _ in
            self?.pollForPageChange()
        }
        pageObservationTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func stopGrounding() {
        pageObservationTimer?.invalidate()
        pageObservationTimer = nil
        lastObservedFingerprint = ""
        isAutoInspectQueued = false
        queuedInspectRequested = false
        queuedInspectCapsule = nil
        activeInspectToken = nil
        inspectTimeoutWorkItem?.cancel()
        inspectTimeoutWorkItem = nil
        suppressGroundingUntil = .distantPast
        lastDoorDashStorefrontWarmupURL = ""
        doorDashStorefrontWarmupAttempts = 0
    }

    func navigate(to url: URL, autoInspect: Bool = false, capsule: ActionCapsule? = nil) {
        websiteState = nil
        inspectionStatus = ""
        searchActionStatus = ""
        buttonActionStatus = ""
        shouldAutoInspectAfterNavigation = autoInspect
        autoInspectCapsule = capsule
        observationCapsule = capsule
        lastObservedFingerprint = ""
        queuedInspectRequested = false
        queuedInspectCapsule = nil
        activeInspectToken = nil
        inspectTimeoutWorkItem?.cancel()
        inspectTimeoutWorkItem = nil
        suppressGroundingUntil = .distantPast
        lastDoorDashStorefrontWarmupURL = ""
        doorDashStorefrontWarmupAttempts = 0
        webView.load(URLRequest(url: url))
        syncState()
    }

    func goBack() {
        if webView.canGoBack {
            webView.goBack()
        }
        syncState()
    }

    func goForward() {
        if webView.canGoForward {
            webView.goForward()
        }
        syncState()
    }

    func reload() {
        webView.reload()
        syncState()
    }

    func inspectPage(capsule: ActionCapsule?) {
        observationCapsule = capsule
        if isInspecting {
            queuedInspectRequested = true
            if let capsule {
                queuedInspectCapsule = capsule
            }
            if inspectionStatus.isEmpty {
                inspectionStatus = "Inspect queued while the current page read finishes..."
            }
            return
        }
        inspectSequence += 1
        let inspectToken = inspectSequence
        activeInspectToken = inspectToken
        inspectTimeoutWorkItem?.cancel()
        isInspecting = true
        inspectionStatus = "Inspecting page..."
        syncState()
        let timeoutWorkItem = DispatchWorkItem { [weak self] in
            guard let self = self, self.activeInspectToken == inspectToken else {
                return
            }
            self.activeInspectToken = nil
            self.isInspecting = false
            self.inspectionStatus = "Inspect timed out. Mirror will retry when the page settles."
            self.flushQueuedInspectIfNeeded()
        }
        inspectTimeoutWorkItem = timeoutWorkItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 10.0, execute: timeoutWorkItem)
        webView.evaluateJavaScript(Self.pageInspectionScript) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                guard self.activeInspectToken == inspectToken else {
                    return
                }
                self.activeInspectToken = nil
                self.inspectTimeoutWorkItem?.cancel()
                self.inspectTimeoutWorkItem = nil
                self.isInspecting = false
                if let error = error {
                    self.inspectionStatus = error.localizedDescription
                    self.flushQueuedInspectIfNeeded()
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.inspectionStatus = "Memla could not read this page yet."
                    self.flushQueuedInspectIfNeeded()
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.inspectionStatus = jsError
                    self.flushQueuedInspectIfNeeded()
                    return
                }
                DispatchQueue.global(qos: .userInitiated).async {
                    let state = Self.buildWebsiteState(payload: payload, capsule: capsule)
                    DispatchQueue.main.async {
                        guard self.activeInspectToken == nil || self.activeInspectToken == inspectToken else {
                            return
                        }
                        self.websiteState = state
                        self.inspectionStatus = "Page inspected."
                        self.maybeWarmDoorDashStorefront(payload: payload, state: state, capsule: capsule)
                        self.flushQueuedInspectIfNeeded()
                    }
                }
            }
        }
    }

    private func flushQueuedInspectIfNeeded() {
        guard queuedInspectRequested else {
            return
        }
        queuedInspectRequested = false
        let capsule = queuedInspectCapsule ?? observationCapsule
        queuedInspectCapsule = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            guard let self = self, !self.isInspecting else {
                return
            }
            self.inspectPage(capsule: capsule)
        }
    }

    private func scheduleDoorDashFollowUpInspect(after delay: TimeInterval, capsule: ActionCapsule?, suppressGroundingFor duration: TimeInterval = 2.8) {
        suppressGroundingUntil = Date().addingTimeInterval(duration)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self else {
                return
            }
            self.inspectPage(capsule: capsule)
        }
    }

    func fillSearchQuery(_ query: String, submit: Bool, capsule: ActionCapsule?) {
        let cleanQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanQuery.isEmpty else {
            searchActionStatus = "No capsule search query is available."
            return
        }
        isRunningSearchAction = true
        searchActionStatus = submit ? "Filling and submitting search..." : "Filling search..."
        webView.evaluateJavaScript(Self.searchFillScript(query: cleanQuery, submit: submit)) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningSearchAction = false
                if let error = error {
                    self.searchActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.searchActionStatus = "Search action returned no page result."
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.searchActionStatus = ok ? reason.capitalized : "Search action blocked: \(reason)"
                if submit {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                        self.inspectPage(capsule: capsule)
                    }
                }
            }
        }
    }

    func fillUberRideLocation(_ query: String, isPickup: Bool, capsule: ActionCapsule?) {
        let cleanQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanQuery.isEmpty else {
            searchActionStatus = "Ride location query is empty."
            return
        }
        isRunningSearchAction = true
        searchActionStatus = isPickup ? "Filling pickup..." : "Filling destination..."
        webView.evaluateJavaScript(Self.uberRideLocationFillScript(query: cleanQuery, isPickup: isPickup)) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningSearchAction = false
                if let error = error {
                    self.searchActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.searchActionStatus = "Ride location fill returned no page result."
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.searchActionStatus = ok ? reason.capitalized : "Ride fill blocked: \(reason)"
                if ok {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) {
                        self.inspectPage(capsule: capsule)
                    }
                }
            }
        }
    }

    func focusUberRideField(isPickup: Bool, capsule: ActionCapsule?) {
        isRunningButtonAction = true
        buttonActionStatus = isPickup ? "Opening pickup field..." : "Opening destination field..."
        webView.evaluateJavaScript(Self.uberRideFieldFocusScript(isPickup: isPickup)) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Field focus returned no page result."
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.buttonActionStatus = ok ? reason.capitalized : "Field focus blocked: \(reason)"
                if ok {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
                        self.inspectPage(capsule: capsule)
                    }
                }
            }
        }
    }

    func tapButtonCandidate(_ candidate: WebsiteC2ACandidate, allowCaution: Bool = false, capsule: ActionCapsule?) {
        let canTap = candidate.tapSafety == "safe" || (allowCaution && candidate.tapSafety == "caution")
        guard canTap, candidate.kind == "button", candidate.url.isEmpty else {
            buttonActionStatus = "Button tap blocked by policy: \(candidate.tapReason)"
            return
        }
        isRunningButtonAction = true
        buttonActionStatus = candidate.tapSafety == "caution" ? "Tapping reviewed button..." : "Tapping safe button..."
        webView.evaluateJavaScript(Self.buttonTapScript(domIndex: candidate.domIndex, allowCaution: allowCaution)) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Button tap returned no page result."
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.buttonActionStatus = jsError
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.buttonActionStatus = ok ? reason.capitalized : "Button tap blocked: \(reason)"
                if ok {
                    self.suppressGroundingUntil = Date().addingTimeInterval(3.0)
                    let inspectDelay: TimeInterval
                    switch candidate.role {
                    case "dd_item_card", "dd_modifier_option", "dd_modifier_save":
                        inspectDelay = 1.35
                    default:
                        inspectDelay = 0.9
                    }
                    DispatchQueue.main.asyncAfter(deadline: .now() + inspectDelay) {
                        self.inspectPage(capsule: capsule)
                    }
                }
            }
        }
    }

    func tapDoorDashResolvedModifierOption(_ candidate: WebsiteC2ACandidate, capsule: ActionCapsule?) {
        isRunningButtonAction = true
        buttonActionStatus = "Tapping reviewed button..."
        let script = Self.doorDashModifierOptionTapScript(
            label: candidate.label,
            groupKey: candidate.groupKey,
            groupLabel: candidate.groupLabel,
            tapFingerprint: candidate.tapFingerprint
        )
        webView.evaluateJavaScript(script) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Button tap returned no page result."
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.buttonActionStatus = jsError
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                let selectedAfterTap = payload["selected_after_tap"] as? Bool ?? false
                if ok {
                    self.buttonActionStatus = selectedAfterTap
                        ? "Tapped Doordash Modifier Option Verified"
                        : reason.capitalized
                } else {
                    self.buttonActionStatus = "Button tap blocked: \(reason)"
                }
                if ok {
                    self.scheduleDoorDashFollowUpInspect(after: 1.35, capsule: capsule)
                }
            }
        }
    }

    func tapDoorDashModifierSave(capsule: ActionCapsule?) {
        isRunningButtonAction = true
        buttonActionStatus = "Saving options..."
        webView.evaluateJavaScript(Self.doorDashModifierSaveScript) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Save tap returned no page result."
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.buttonActionStatus = jsError
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.buttonActionStatus = ok ? reason.capitalized : "Save tap blocked: \(reason)"
                if ok {
                    self.scheduleDoorDashFollowUpInspect(after: 1.35, capsule: capsule, suppressGroundingFor: 3.2)
                }
            }
        }
    }

    func tapDoorDashAddToCart(capsule: ActionCapsule?) {
        isRunningButtonAction = true
        buttonActionStatus = "Adding item to cart..."
        webView.evaluateJavaScript(Self.doorDashAddToCartScript) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Add-to-cart tap returned no page result."
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.buttonActionStatus = jsError
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.buttonActionStatus = ok ? reason.capitalized : "Add-to-cart tap blocked: \(reason)"
                if ok {
                    self.scheduleDoorDashFollowUpInspect(after: 1.1, capsule: capsule, suppressGroundingFor: 2.8)
                }
            }
        }
    }

    func tapDoorDashContinueToCheckout(capsule: ActionCapsule?) {
        isRunningButtonAction = true
        buttonActionStatus = "Continuing to checkout..."
        webView.evaluateJavaScript(Self.doorDashContinueToCheckoutScript) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self else {
                    return
                }
                self.isRunningButtonAction = false
                if let error = error {
                    self.buttonActionStatus = error.localizedDescription
                    return
                }
                guard let payload = result as? [String: Any] else {
                    self.buttonActionStatus = "Continue tap returned no page result."
                    return
                }
                if let jsError = Self.javaScriptPayloadError(payload) {
                    self.buttonActionStatus = jsError
                    return
                }
                let reason = Self.stringValue(payload["reason"]).replacingOccurrences(of: "_", with: " ")
                let ok = payload["ok"] as? Bool ?? false
                self.buttonActionStatus = ok ? reason.capitalized : "Continue tap blocked: \(reason)"
                if ok {
                    self.scheduleDoorDashFollowUpInspect(after: 1.1, capsule: capsule, suppressGroundingFor: 2.4)
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        websiteState = nil
        inspectionStatus = ""
        searchActionStatus = ""
        buttonActionStatus = ""
        lastObservedFingerprint = ""
        syncState()
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        syncState()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        syncState()
        if shouldAutoInspectAfterNavigation {
            shouldAutoInspectAfterNavigation = false
            let capsule = autoInspectCapsule
            autoInspectCapsule = nil
            inspectionStatus = "Auto-inspecting next page..."
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                self?.inspectPage(capsule: capsule)
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        syncState()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        syncState()
    }

    private func syncState() {
        let cleanTitle = webView.title?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let cleanTitle = cleanTitle, !cleanTitle.isEmpty {
            pageTitle = cleanTitle
        } else {
            pageTitle = "Untitled"
        }
        currentURL = webView.url?.absoluteString ?? ""
        isLoading = webView.isLoading
        canGoBack = webView.canGoBack
        canGoForward = webView.canGoForward
    }

    private func pollForPageChange() {
        guard Date() >= suppressGroundingUntil else {
            return
        }
        guard !isInspecting, !isLoading, !isRunningButtonAction, webView.url != nil else {
            return
        }
        webView.evaluateJavaScript(Self.pageGroundingProbeScript) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self, error == nil, let payload = result as? [String: Any] else {
                    return
                }
                let fingerprint = Self.stringValue(payload["fingerprint"])
                guard !fingerprint.isEmpty else {
                    return
                }
                if self.lastObservedFingerprint.isEmpty {
                    self.lastObservedFingerprint = fingerprint
                    return
                }
                guard fingerprint != self.lastObservedFingerprint else {
                    return
                }
                self.lastObservedFingerprint = fingerprint
                self.queueAutoInspect(reason: "Mirror detected a page change...")
            }
        }
    }

    private func queueAutoInspect(reason: String) {
        guard Date() >= suppressGroundingUntil else {
            return
        }
        guard !isAutoInspectQueued, !isInspecting, !isRunningButtonAction else {
            return
        }
        isAutoInspectQueued = true
        inspectionStatus = reason
        let capsule = observationCapsule
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { [weak self] in
            guard let self = self else {
                return
            }
            self.isAutoInspectQueued = false
            self.inspectPage(capsule: capsule)
        }
    }

    private func maybeWarmDoorDashStorefront(payload: [String: Any], state: WebsiteC2AState, capsule: ActionCapsule?) {
        guard state.pageKind == "dd_storefront" else {
            return
        }
        let itemCount = payload["doordash_item_card_count"] as? Int ?? 0
        guard itemCount < 10 else {
            lastDoorDashStorefrontWarmupURL = currentURL
            doorDashStorefrontWarmupAttempts = 0
            return
        }
        let url = currentURL
        guard !url.isEmpty else {
            return
        }
        if lastDoorDashStorefrontWarmupURL != url {
            lastDoorDashStorefrontWarmupURL = url
            doorDashStorefrontWarmupAttempts = 0
        }
        guard doorDashStorefrontWarmupAttempts < 3 else {
            return
        }
        doorDashStorefrontWarmupAttempts += 1
        inspectionStatus = "Memla is peeking into the DoorDash menu..."
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1) { [weak self] in
            guard let self = self else {
                return
            }
            guard self.currentURL == url, !self.isLoading else {
                return
            }
            self.webView.evaluateJavaScript(Self.doorDashStorefrontPeekScript) { [weak self] _, _ in
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    self?.inspectPage(capsule: capsule)
                }
            }
        }
    }

    private static func buildWebsiteState(payload: [String: Any], capsule: ActionCapsule?) -> WebsiteC2AState {
        let title = stringValue(payload["title"])
        let url = stringValue(payload["url"])
        let textSnippet = stringValue(payload["text_snippet"])
        let headings = stringArray(payload["headings"])
        let inputs = stringArray(payload["inputs"])
        let buttons = stringArray(payload["buttons"])
        let links = stringArray(payload["links"])
        let combined = ([title, url, textSnippet] + headings + inputs + buttons + links).joined(separator: " ").lowercased()
        let normalizedCombined = normalizedText(combined)
        let isDoorDash = isDoorDashDomain(url: url)
        let isUberEats = isUberEatsDomain(url: url)
        let isUberRide = isUberRideDomain(url: url)
        let pageKind: String
        if isDoorDash {
            pageKind = classifyDoorDashPage(payload: payload, combined: combined, url: url, inputs: inputs)
        } else if isUberEats {
            pageKind = classifyUberEatsPage(payload: payload, combined: combined, url: url, inputs: inputs)
        } else if isUberRide {
            pageKind = classifyUberRidePage(payload: payload, combined: combined, url: url, inputs: inputs)
        } else {
            pageKind = classifyPageKind(combined: combined, url: url, inputs: inputs)
        }
        let candidateSource: Any?
        if isDoorDash {
            candidateSource = payload["doordash_candidates"] ?? payload["candidates"]
        } else if isUberEats {
            candidateSource = payload["ubereats_candidates"] ?? payload["candidates"]
        } else if isUberRide {
            candidateSource = payload["uber_candidates"] ?? payload["candidates"]
        } else {
            candidateSource = payload["candidates"]
        }
        var candidates = candidateArray(candidateSource, capsule: capsule, pageKind: pageKind)
        if isDoorDash {
            candidates = enrichDoorDashCandidates(candidates, pageKind: pageKind, buttons: buttons)
        }
        let safeActions = candidateActions(pageKind: pageKind, inputs: inputs, buttons: buttons, links: links, candidates: candidates)
        let residuals = residualsForPage(payload: payload, pageKind: pageKind, combined: normalizedCombined, textSnippet: textSnippet, capsule: capsule)
        let authState = classifyAuthState(pageKind: pageKind, combined: combined)
        let authDomain = domainFrom(url: url)
        let capsuleVerification = capsuleVerificationForPage(pageKind: pageKind, combined: normalizedCombined, capsule: capsule)
        let serviceFacts: [String: String]
        let summary: String
        if isDoorDash {
            serviceFacts = doorDashFacts(payload: payload)
            summary = doorDashSummary(payload: payload, pageKind: pageKind, candidates: candidates)
        } else if isUberEats {
            serviceFacts = [:]
            summary = uberEatsSummary(payload: payload, pageKind: pageKind, candidates: candidates)
        } else if isUberRide {
            serviceFacts = uberRideFacts(payload: payload)
            summary = uberRideSummary(payload: payload, pageKind: pageKind, candidates: candidates)
        } else {
            serviceFacts = [:]
            summary = "Compiled \(pageKind.replacingOccurrences(of: "_", with: " ")) with \(inputs.count) inputs, \(buttons.count) buttons, \(links.count) links, and \(candidates.count) candidates."
        }
        return WebsiteC2AState(
            pageKind: pageKind,
            summary: summary,
            headings: headings,
            inputs: inputs,
            buttons: buttons,
            links: links,
            candidates: candidates,
            safeActions: safeActions,
            residuals: residuals,
            authState: authState,
            authDomain: authDomain,
            textSnippet: textSnippet,
            serviceFacts: serviceFacts,
            capsuleVerification: capsuleVerification
        )
    }

    private static func isDoorDashDomain(url: String) -> Bool {
        domainFrom(url: url).contains("doordash.com")
    }

    private static func enrichDoorDashCandidates(_ candidates: [WebsiteC2ACandidate], pageKind: String, buttons: [String]) -> [WebsiteC2ACandidate] {
        guard pageKind == "dd_item_modal" else {
            return candidates
        }
        let normalizedButtons = buttons.map(normalizedText)
        var enriched = candidates

        if !enriched.contains(where: { $0.role == "dd_add_to_cart" }),
           let addLabel = buttons.first(where: {
               let normalized = normalizedText($0)
               return normalized.contains("add to cart") || normalized.contains("update item")
           }) {
            enriched.append(
                WebsiteC2ACandidate(
                    id: "synthetic-dd-add-to-cart",
                    domIndex: -1,
                    label: addLabel,
                    url: "",
                    kind: "button",
                    role: "dd_add_to_cart",
                    score: 5.1,
                    matchedTerms: [],
                    blocked: false,
                    tapSafety: "caution",
                    tapReason: "Needs user review before Memla taps",
                    reason: "DoorDash add-to-cart control"
                )
            )
        }

        guard !enriched.contains(where: { $0.role == "dd_modifier_save" }),
              !enriched.contains(where: { $0.role == "dd_add_to_cart" }) else {
            return enriched
        }
        let saveLabel: String?
        if normalizedButtons.contains(where: { $0 == "save" }) {
            saveLabel = "Save"
        } else if normalizedButtons.contains(where: { $0.contains("save options") }) {
            saveLabel = "Save Options"
        } else if normalizedButtons.contains(where: { $0.contains("save") }) {
            saveLabel = "Save"
        } else {
            saveLabel = nil
        }
        guard let saveLabel else {
            return enriched
        }
        enriched.append(
            WebsiteC2ACandidate(
                id: "synthetic-dd-modifier-save",
                domIndex: -1,
                label: saveLabel,
                url: "",
                kind: "button",
                role: "dd_modifier_save",
                score: 5.2,
                matchedTerms: [],
                blocked: false,
                tapSafety: "safe",
                tapReason: "DoorDash customizer save footer",
                reason: "DoorDash save-options control"
            )
        )
        return enriched
    }

    private static func isUberEatsDomain(url: String) -> Bool {
        domainFrom(url: url).contains("ubereats.com")
    }

    private static func isUberRideDomain(url: String) -> Bool {
        let domain = domainFrom(url: url)
        return domain.contains("uber.com") && !domain.contains("ubereats.com")
    }

    private static func doorDashFacts(payload: [String: Any]) -> [String: String] {
        var facts: [String: String] = [:]
        let addToCartLabel = stringValue(payload["doordash_customizer_add_to_cart_label"])
        let hasAddToCart = payload["doordash_has_add_to_cart_cta"] as? Bool ?? false
        let hasCartCTA = payload["doordash_has_cart_cta"] as? Bool ?? false
        let hasContinueCTA = payload["doordash_has_continue_cta"] as? Bool ?? false
        let activeLayer = stringValue(payload["doordash_active_layer"])
        let modalTitle = stringValue(payload["doordash_modal_title"])
        let activeGroupKey = stringValue(payload["doordash_customizer_active_group_key"])
        let activeGroupLabel = stringValue(payload["doordash_customizer_active_group_label"])
        let activeGroupRequired = payload["doordash_customizer_active_group_required"] as? Bool ?? false
        let checkedRadioCount = payload["doordash_customizer_checked_radio_count"] as? Int ?? 0
        let checkedCheckboxCount = payload["doordash_customizer_checked_checkbox_count"] as? Int ?? 0
        facts["dd_has_add_to_cart"] = hasAddToCart ? "true" : "false"
        facts["dd_has_cart_cta"] = hasCartCTA ? "true" : "false"
        facts["dd_has_continue_cta"] = hasContinueCTA ? "true" : "false"
        facts["dd_checked_radio_count"] = String(checkedRadioCount)
        facts["dd_checked_checkbox_count"] = String(checkedCheckboxCount)
        if !addToCartLabel.isEmpty {
            facts["dd_add_to_cart_label"] = addToCartLabel
        }
        if !activeLayer.isEmpty {
            facts["dd_active_layer"] = activeLayer
        }
        if !modalTitle.isEmpty {
            facts["dd_modal_title"] = modalTitle
        }
        if !activeGroupKey.isEmpty {
            facts["dd_active_group_key"] = activeGroupKey
        }
        if !activeGroupLabel.isEmpty {
            facts["dd_active_group_label"] = activeGroupLabel
        }
        facts["dd_active_group_required"] = activeGroupRequired ? "true" : "false"
        return facts
    }

    private static func classifyDoorDashPage(payload: [String: Any], combined: String, url: String, inputs: [String]) -> String {
        let layerKind = stringValue(payload["doordash_active_layer"])
        let modalTitle = normalizedText(stringValue(payload["doordash_modal_title"]))
        let hasStoreCards = (payload["doordash_store_card_count"] as? Int ?? 0) > 0
        let hasCartCTA = payload["doordash_has_cart_cta"] as? Bool ?? false
        let hasContinueCTA = payload["doordash_has_continue_cta"] as? Bool ?? false
        let hasAddToCartCTA = payload["doordash_has_add_to_cart_cta"] as? Bool ?? false
        let tipCount = payload["doordash_tip_option_count"] as? Int ?? 0
        let hasPaymentSheet = payload["doordash_has_payment_sheet"] as? Bool ?? false
        let hasAddressCTA = payload["doordash_has_address_cta"] as? Bool ?? false
        let hasCartCloseCTA = payload["doordash_has_cart_close_cta"] as? Bool ?? false

        if hasPaymentSheet || layerKind == "payment_sheet" || combined.contains("select payment method") {
            return "dd_payment_sheet"
        }
        if url.contains("/consumer/checkout") {
            return "dd_checkout"
        }
        if layerKind == "cart_drawer" || hasContinueCTA || hasCartCloseCTA {
            return "dd_cart_drawer"
        }
        if layerKind == "item_modal" || (!modalTitle.isEmpty && layerKind != "page") {
            return "dd_item_modal"
        }
        if hasStoreCards || url.contains("/search/store/") {
            return "dd_search_results"
        }
        if url.contains("/store/") {
            return "dd_storefront"
        }
        if hasContinueCTA || tipCount > 0 || hasAddressCTA {
            return "dd_cart_page"
        }
        return classifyPageKind(combined: combined, url: url, inputs: inputs)
    }

    private static func doorDashSummary(payload: [String: Any], pageKind: String, candidates: [WebsiteC2ACandidate]) -> String {
        let storeCardCount = payload["doordash_store_card_count"] as? Int ?? 0
        let itemCardCount = payload["doordash_item_card_count"] as? Int ?? 0
        let tipCount = payload["doordash_tip_option_count"] as? Int ?? 0
        let customizerGroupCount = payload["doordash_customizer_group_count"] as? Int ?? 0
        let customizerRequiredGroupCount = payload["doordash_customizer_required_group_count"] as? Int ?? 0
        let checkedRadioCount = payload["doordash_customizer_checked_radio_count"] as? Int ?? 0
        let checkedCheckboxCount = payload["doordash_customizer_checked_checkbox_count"] as? Int ?? 0
        let presetCount = payload["doordash_customizer_recommended_preset_count"] as? Int ?? 0
        let addToCartLabel = stringValue(payload["doordash_customizer_add_to_cart_label"])
        let hasSpecialInstructions = payload["doordash_customizer_has_special_instructions"] as? Bool ?? false
        let layerKind = stringValue(payload["doordash_active_layer"])
        let modalTitle = stringValue(payload["doordash_modal_title"])
        switch pageKind {
        case "dd_search_results":
            return "DoorDash search results distilled into \(storeCardCount) store cards."
        case "dd_storefront":
            return "DoorDash storefront with \(itemCardCount) relevant item/menu cards."
        case "dd_item_modal":
            var parts: [String] = []
            if !modalTitle.isEmpty {
                parts.append(modalTitle)
            }
            if customizerRequiredGroupCount > 0 {
                parts.append("\(customizerRequiredGroupCount) required groups")
            } else if customizerGroupCount > 0 {
                parts.append("\(customizerGroupCount) modifier groups")
            }
            if checkedRadioCount > 0 {
                parts.append("\(checkedRadioCount) selections already chosen")
            }
            if checkedCheckboxCount > 0 {
                parts.append("\(checkedCheckboxCount) optional toggles selected")
            }
            if presetCount > 0 {
                parts.append("\(presetCount) recommended presets")
            }
            if hasSpecialInstructions {
                parts.append("special instructions available")
            }
            if !addToCartLabel.isEmpty {
                parts.append(addToCartLabel)
            }
            if parts.isEmpty {
                return "DoorDash item modal detected."
            }
            return "DoorDash item modal: \(parts.joined(separator: " • "))."
        case "dd_cart_drawer":
            return "DoorDash cart drawer is active with a continue path."
        case "dd_cart_page":
            return "DoorDash cart page detected with \(tipCount) tip options."
        case "dd_checkout":
            return "DoorDash checkout detected. Mirror should stop before payment."
        case "dd_payment_sheet":
            return "DoorDash payment sheet is active. Human confirmation boundary reached."
        default:
            return "DoorDash \(pageKind.replacingOccurrences(of: "_", with: " ")) layer \(layerKind) with \(candidates.count) candidates."
        }
    }

    private static func classifyUberEatsPage(payload: [String: Any], combined: String, url: String, inputs: [String]) -> String {
        let layerKind = stringValue(payload["ubereats_active_layer"])
        let hasStoreCards = (payload["ubereats_store_card_count"] as? Int ?? 0) > 0
        let hasItemCards = (payload["ubereats_item_card_count"] as? Int ?? 0) > 0
        let hasCartCTA = payload["ubereats_has_cart_cta"] as? Bool ?? false
        let hasContinueCTA = payload["ubereats_has_continue_cta"] as? Bool ?? false
        let hasAddToCartCTA = payload["ubereats_has_add_to_cart_cta"] as? Bool ?? false
        let hasAddressGate = payload["ubereats_has_address_gate"] as? Bool ?? false
        let hasContinueBrowser = payload["ubereats_has_continue_browser"] as? Bool ?? false
        let hasSearchEntry = payload["ubereats_has_search_entry"] as? Bool ?? false

        if url.contains("/checkout") || combined.contains("continue to payment") || combined.contains("order summary") {
            return "ue_checkout"
        }
        if layerKind == "item_modal" {
            return "ue_item_modal"
        }
        if hasContinueCTA || hasCartCTA {
            return "ue_cart_page"
        }
        if hasStoreCards || url.contains("/search") {
            return "ue_search_results"
        }
        if hasItemCards || url.contains("/store/") {
            return "ue_storefront"
        }
        if hasContinueBrowser || hasAddressGate || hasSearchEntry {
            return "ue_entry_gate"
        }
        return classifyPageKind(combined: combined, url: url, inputs: inputs)
    }

    private static func uberEatsSummary(payload: [String: Any], pageKind: String, candidates: [WebsiteC2ACandidate]) -> String {
        let storeCardCount = payload["ubereats_store_card_count"] as? Int ?? 0
        let itemCardCount = payload["ubereats_item_card_count"] as? Int ?? 0
        let layerKind = stringValue(payload["ubereats_active_layer"])
        switch pageKind {
        case "ue_entry_gate":
            return "Uber Eats entry gate detected. Continue in browser or address setup is still in front of the food flow."
        case "ue_search_results":
            return "Uber Eats search results distilled into \(storeCardCount) store cards."
        case "ue_storefront":
            return "Uber Eats storefront with \(itemCardCount) relevant menu items."
        case "ue_item_modal":
            return "Uber Eats item customizer is active."
        case "ue_cart_page":
            return "Uber Eats cart is ready to advance."
        case "ue_checkout":
            return "Uber Eats checkout detected. Mirror should stop before payment."
        default:
            return "Uber Eats \(pageKind.replacingOccurrences(of: "_", with: " ")) layer \(layerKind) with \(candidates.count) candidates."
        }
    }

    private static func classifyUberRidePage(payload: [String: Any], combined: String, url: String, inputs: [String]) -> String {
        let hasPickupInput = payload["uber_has_pickup_input"] as? Bool ?? false
        let hasDropoffInput = payload["uber_has_dropoff_input"] as? Bool ?? false
        let pickupResults = payload["uber_pickup_result_count"] as? Int ?? 0
        let dropoffResults = payload["uber_dropoff_result_count"] as? Int ?? 0
        let hasSeePricesCTA = payload["uber_has_see_prices_cta"] as? Bool ?? false
        let hasRequestCTA = payload["uber_has_request_cta"] as? Bool ?? false
        let vehicleCount = payload["uber_vehicle_option_count"] as? Int ?? 0
        let hasRideBuilderHints = combined.contains("pickup location needs to be filled in")
            || combined.contains("dropoff location needs to be filled in")
            || combined.contains("see prices")
            || (combined.contains("pickup now") && combined.contains("for me"))
        let hasProductSelectionHints = combined.contains("request uber")
            || combined.contains("request trip")
            || combined.contains("add payment method")
            || (combined.contains("uberx") && combined.contains("$"))

        if url.contains("/go/product-selection") || hasRequestCTA || vehicleCount > 0 || hasProductSelectionHints {
            return "ub_product_selection"
        }
        if hasPickupInput || hasDropoffInput || pickupResults > 0 || dropoffResults > 0 || hasSeePricesCTA || url.contains("/start-riding") || url.contains("/looking") || hasRideBuilderHints {
            return "ub_trip_builder"
        }
        return classifyPageKind(combined: combined, url: url, inputs: inputs)
    }

    private static func uberRideSummary(payload: [String: Any], pageKind: String, candidates: [WebsiteC2ACandidate]) -> String {
        let pickupResults = payload["uber_pickup_result_count"] as? Int ?? 0
        let dropoffResults = payload["uber_dropoff_result_count"] as? Int ?? 0
        let vehicleCount = payload["uber_vehicle_option_count"] as? Int ?? 0
        switch pageKind {
        case "ub_trip_builder":
            return "Uber trip builder detected with \(pickupResults + dropoffResults) location results and ride setup controls."
        case "ub_product_selection":
            return "Uber product selection is visible with \(vehicleCount) ride options. Stop before the final request button."
        default:
            return "Uber ride flow with \(candidates.count) candidates."
        }
    }

    private static func uberRideFacts(payload: [String: Any]) -> [String: String] {
        [
            "ub_pickup_missing": String(payload["uber_pickup_missing"] as? Bool ?? false),
            "ub_dropoff_missing": String(payload["uber_dropoff_missing"] as? Bool ?? false),
            "ub_pickup_value": stringValue(payload["uber_pickup_value"]),
            "ub_dropoff_value": stringValue(payload["uber_dropoff_value"]),
            "ub_has_request_cta": String(payload["uber_has_request_cta"] as? Bool ?? false),
            "ub_has_see_prices_cta": String(payload["uber_has_see_prices_cta"] as? Bool ?? false),
        ]
    }

    private static func classifyPageKind(combined: String, url: String, inputs: [String]) -> String {
        if combined.contains("captcha") || combined.contains("verify you are human") {
            return "blocked_or_bot_check"
        }
        if combined.contains("sign in") || combined.contains("log in") || combined.contains("login") {
            return "login"
        }
        if combined.contains("place order")
            || combined.contains("submit order")
            || combined.contains("complete order")
            || combined.contains("confirm order")
            || combined.contains("pay now")
            || combined.contains("card number")
            || combined.contains("cvv")
            || combined.contains("payment method")
            || combined.contains("payment information") {
            return "checkout"
        }
        if combined.contains("add to cart") || combined.contains("customize") || combined.contains("toppings") || combined.contains("menu") {
            return "menu_or_item"
        }
        if combined.contains("cart") || combined.contains("subtotal") || combined.contains("tip") || combined.contains("checkout") {
            return "cart"
        }
        if combined.contains("results for") || combined.contains("search results") || url.contains("/search") {
            return "search_results"
        }
        if inputs.contains(where: { $0.lowercased().contains("search") }) {
            return "search_form"
        }
        return "web_page"
    }

    private static func candidateActions(pageKind: String, inputs: [String], buttons: [String], links: [String], candidates: [WebsiteC2ACandidate]) -> [String] {
        var actions: [String] = []
        if pageKind == "ub_trip_builder" {
            actions.append("set_trip_locations")
            actions.append("review_then_tap_candidate")
        }
        if pageKind == "ub_product_selection" {
            actions.append("review_trip_quote")
            actions.append("stop_before_request")
        }
        if pageKind == "dd_search_results" {
            actions.append("open_ranked_candidate")
        }
        if pageKind == "ue_entry_gate" {
            actions.append("inspect_visible_candidates")
        }
        if pageKind == "ue_search_results" {
            actions.append("open_ranked_candidate")
        }
        if pageKind == "ue_storefront" {
            actions.append("open_ranked_candidate")
            actions.append("review_item_and_modifiers")
        }
        if pageKind == "ue_item_modal" {
            actions.append("review_item_and_modifiers")
            actions.append("review_then_tap_candidate")
        }
        if pageKind == "ue_cart_page" {
            actions.append("verify_cart_against_capsule")
            actions.append("review_then_enter_checkout")
        }
        if pageKind == "ue_checkout" {
            actions.append("stop_before_purchase")
        }
        if pageKind == "dd_storefront" {
            actions.append("open_ranked_candidate")
            actions.append("review_item_and_modifiers")
        }
        if pageKind == "dd_item_modal" {
            actions.append("review_item_and_modifiers")
            actions.append("review_then_tap_candidate")
        }
        if pageKind == "dd_cart_drawer" || pageKind == "dd_cart_page" {
            actions.append("verify_cart_against_capsule")
            actions.append("review_then_enter_checkout")
        }
        if pageKind == "dd_checkout" || pageKind == "dd_payment_sheet" {
            actions.append("stop_before_purchase")
        }
        if pageKind == "search_form" || inputs.contains(where: { $0.lowercased().contains("search") }) {
            actions.append("fill_search_query")
        }
        if pageKind == "search_results" && !links.isEmpty {
            actions.append("select_matching_candidate")
        }
        if candidates.contains(where: { !$0.blocked && !$0.url.isEmpty && $0.score > 0 }) {
            actions.append("open_ranked_candidate")
        }
        if candidates.contains(where: { $0.kind == "button" && $0.url.isEmpty && $0.tapSafety == "safe" }) {
            actions.append("tap_safe_button_candidate")
        }
        if candidates.contains(where: { $0.kind == "button" && $0.url.isEmpty && $0.tapSafety == "caution" }) {
            actions.append("review_then_tap_candidate")
        }
        if pageKind == "menu_or_item" {
            actions.append("review_item_and_modifiers")
        }
        if pageKind == "cart" {
            actions.append("verify_cart_against_capsule")
            actions.append("review_then_enter_checkout")
        }
        if pageKind == "checkout" {
            actions.append("stop_before_purchase")
        }
        if buttons.contains(where: { $0.lowercased().contains("filter") || $0.lowercased().contains("apply") }) {
            actions.append("use_filter_control")
        }
        if actions.isEmpty && (!buttons.isEmpty || !links.isEmpty) {
            actions.append("inspect_visible_candidates")
        }
        return Array(dictUnique(actions))
    }

    private static func residualsForPage(payload: [String: Any], pageKind: String, combined: String, textSnippet: String, capsule: ActionCapsule?) -> [String] {
        var residuals: [String] = []
        if pageKind == "ub_trip_builder" {
            residuals.append("trip_builder_active")
            if payload["uber_pickup_missing"] as? Bool ?? false {
                residuals.append("pickup_location_not_verified")
            }
            if payload["uber_dropoff_missing"] as? Bool ?? false {
                residuals.append("destination_not_verified")
            }
        }
        if pageKind == "ub_product_selection" {
            residuals.append("ride_request_ready")
            residuals.append("final_confirmation_required")
            residuals.append("irreversible_action_nearby")
        }
        if pageKind == "dd_payment_sheet" {
            residuals.append("payment_sheet_active")
            residuals.append("final_confirmation_required")
            residuals.append("irreversible_action_nearby")
        }
        if pageKind == "ue_entry_gate" {
            residuals.append("address_or_browser_gate")
        }
        if pageKind == "ue_item_modal" {
            residuals.append("active_customizer_layer")
        }
        if pageKind == "ue_cart_page" {
            residuals.append("cart_verification_required")
        }
        if pageKind == "ue_checkout" {
            residuals.append("final_confirmation_required")
            residuals.append("irreversible_action_nearby")
        }
        if pageKind == "dd_item_modal" {
            residuals.append("active_customizer_layer")
        }
        if pageKind == "dd_cart_drawer" {
            residuals.append("cart_drawer_active")
        }
        if pageKind == "login" {
            residuals.append("login_required")
        }
        if pageKind == "blocked_or_bot_check" {
            residuals.append("bot_check_or_captcha")
        }
        if pageKind == "checkout" {
            residuals.append("irreversible_action_nearby")
            residuals.append("final_confirmation_required")
        }
        if pageKind == "cart" {
            residuals.append("cart_verification_required")
        }
        if textSnippet.isEmpty {
            residuals.append("visible_text_empty")
        }
        if let capsule = capsule {
            let restaurant = normalizedText(capsule.slots["restaurant"] ?? "")
            if !restaurant.isEmpty && !combined.contains(restaurant) {
                residuals.append("target_restaurant_not_visible")
            }
            let item = normalizedText(capsule.slots["item"] ?? "")
            if !item.isEmpty && !combined.contains(item) {
                residuals.append("target_item_not_visible")
            }
        }
        return Array(dictUnique(residuals))
    }

    private static func capsuleVerificationForPage(pageKind: String, combined: String, capsule: ActionCapsule?) -> WebsiteCapsuleVerification? {
        guard let capsule = capsule else {
            return nil
        }
        let relevantPages = ["menu_or_item", "cart", "checkout", "dd_storefront", "dd_item_modal", "dd_cart_drawer", "dd_cart_page", "dd_checkout", "dd_payment_sheet", "ue_storefront", "ue_item_modal", "ue_cart_page", "ue_checkout", "ub_trip_builder", "ub_product_selection"]
        guard relevantPages.contains(pageKind) else {
            return nil
        }
        var matched: [String] = []
        var missing: [String] = []
        var warnings: [String] = []

        func verifySlot(_ key: String, label: String? = nil) {
            let raw = capsule.slots[key]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !raw.isEmpty else {
                return
            }
            let readable = label ?? key.replacingOccurrences(of: "_", with: " ")
            let parts: [String]
            if key == "modifiers" || key == "toppings" || key == "add_ons" {
                parts = raw
                    .replacingOccurrences(of: " and ", with: ",")
                    .components(separatedBy: CharacterSet(charactersIn: ",/+&"))
            } else {
                parts = [raw]
            }
            let normalizedParts = parts
                .map { normalizedText($0) }
                .filter { !$0.isEmpty }
            guard !normalizedParts.isEmpty else {
                return
            }
            let foundParts = normalizedParts.filter { combined.contains($0) }
            if foundParts.isEmpty {
                missing.append(readable)
            } else if foundParts.count == normalizedParts.count {
                matched.append(readable)
            } else {
                matched.append(readable)
                missing.append("\(readable) partial")
            }
        }

        verifySlot("restaurant")
        verifySlot("item")
        verifySlot("size")
        verifySlot("modifiers")
        verifySlot("toppings")
        verifySlot("add_ons", label: "add ons")
        verifySlot("tip")
        verifySlot("destination")
        verifySlot("pickup_time")

        if pageKind == "menu_or_item" {
            warnings.append("review_item_options_before_cart")
        }
        if pageKind == "ub_trip_builder" {
            warnings.append("verify_pickup_and_destination_before_price_quote")
        }
        if pageKind == "ub_product_selection" {
            warnings.append("human_must_confirm_final_ride_request")
        }
        if pageKind == "dd_storefront" || pageKind == "dd_item_modal" {
            warnings.append("review_item_options_before_cart")
        }
        if pageKind == "ue_storefront" || pageKind == "ue_item_modal" {
            warnings.append("review_item_options_before_cart")
        }
        if pageKind == "cart" {
            warnings.append("verify_cart_before_checkout")
            warnings.append("checkout_is_reviewed_navigation_only")
        }
        if pageKind == "dd_cart_drawer" || pageKind == "dd_cart_page" {
            warnings.append("verify_cart_before_checkout")
            warnings.append("checkout_is_reviewed_navigation_only")
        }
        if pageKind == "ue_cart_page" {
            warnings.append("verify_cart_before_checkout")
            warnings.append("checkout_is_reviewed_navigation_only")
        }
        if pageKind == "checkout" {
            warnings.append("human_must_complete_final_payment_or_place_order")
        }
        if pageKind == "dd_checkout" || pageKind == "dd_payment_sheet" {
            warnings.append("human_must_complete_final_payment_or_place_order")
        }
        if pageKind == "ue_checkout" {
            warnings.append("human_must_complete_final_payment_or_place_order")
        }

        let summary: String
        if missing.isEmpty {
            summary = "Capsule terms are visible. Continue only after reviewing item, modifiers, tip, address, and total."
        } else {
            summary = "Missing visible evidence for \(missing.joined(separator: ", ")). Review before continuing."
        }
        return WebsiteCapsuleVerification(
            matched: Array(dictUnique(matched)),
            missing: Array(dictUnique(missing)),
            warnings: Array(dictUnique(warnings)),
            summary: summary
        )
    }

    private static func classifyAuthState(pageKind: String, combined: String) -> String {
        if pageKind.hasPrefix("ub_") {
            if combined.contains("your account information") || combined.contains("add payment method") || combined.contains("pickup now") || combined.contains("request uber") {
                return "likely_signed_in"
            }
            return "unknown"
        }
        if pageKind == "login" {
            return "login_required"
        }
        let signedInHints = [
            "account",
            "profile",
            "sign out",
            "log out",
            "orders",
            "your address",
            "deliver to",
            "cart",
            "checkout",
        ]
        if signedInHints.contains(where: { combined.contains($0) }) {
            return "likely_signed_in"
        }
        return "unknown"
    }

    private static func domainFrom(url: String) -> String {
        guard let host = URL(string: url)?.host else {
            return ""
        }
        return host.replacingOccurrences(of: "www.", with: "")
    }

    private static func stringValue(_ value: Any?) -> String {
        if let value = value as? String {
            return value.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return ""
    }

    private static func javaScriptStringLiteral(_ value: String) -> String {
        let escaped = value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
            .replacingOccurrences(of: "\r", with: "")
            .replacingOccurrences(of: "\n", with: "\\n")
        return "'\(escaped)'"
    }

    private static func stringArray(_ value: Any?) -> [String] {
        guard let items = value as? [Any] else {
            return []
        }
        return items.compactMap { item in
            guard let text = item as? String else {
                return nil
            }
            let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return clean.isEmpty ? nil : clean
        }
    }

    private static func candidateArray(_ value: Any?, capsule: ActionCapsule?, pageKind: String) -> [WebsiteC2ACandidate] {
        guard let items = value as? [Any] else {
            return []
        }
        let targets = candidateTargets(from: capsule)
        let candidates = items.enumerated().compactMap { index, item -> WebsiteC2ACandidate? in
            guard let raw = item as? [String: Any] else {
                return nil
            }
            let label = stringValue(raw["label"])
            let url = stringValue(raw["url"])
            let kind = stringValue(raw["kind"])
            let context = stringValue(raw["context"])
            let domIndex = Int(stringValue(raw["id"])) ?? index
            let serviceRole = stringValue(raw["service_role"])
            let groupKey = stringValue(raw["group_key"])
            let groupLabel = stringValue(raw["group_label"])
            let groupRequired = stringValue(raw["group_required"]) == "true"
            let tapFingerprint = stringValue(raw["tap_fingerprint"])
            let isSelected = stringValue(raw["selected"]) == "true"
            let opensSubflow = stringValue(raw["opens_subflow"]) == "true"
            guard !label.isEmpty || !url.isEmpty else {
                return nil
            }
            let candidateText = [label, url, context].joined(separator: " ")
            let ranking = rankCandidate(candidateText, targets: targets)
            let role = serviceRole.isEmpty ? candidateRole(pageKind: pageKind, kind: kind, url: url, label: label, context: context) : serviceRole
            let blockedText = kind == "button" ? label : candidateText
            let blocked = isIrreversibleCandidate(blockedText) || isBlockedServiceRole(role)
            let tapPolicy = buttonTapPolicy(kind: kind, url: url, label: label, context: context, blocked: blocked)
            let adjustedScore = ranking.score + roleScoreAdjustment(role: role) + serviceLabelAdjustment(role: role, label: label, context: context)
            let resolvedLabel = displayLabel(label: label, url: url, context: context, role: role)
            let reason: String
            if blocked {
                reason = "Final or irreversible action nearby"
            } else if ranking.matchedTerms.isEmpty {
                reason = roleReason(role: role)
            } else {
                reason = "Matched \(ranking.matchedTerms.joined(separator: ", ")) via \(role.replacingOccurrences(of: "_", with: " "))"
            }
            return WebsiteC2ACandidate(
                id: "\(kind)-\(index)-\(url)-\(label)",
                domIndex: domIndex,
                label: resolvedLabel,
                url: url,
                kind: kind.isEmpty ? "candidate" : kind,
                role: role,
                score: adjustedScore,
                matchedTerms: ranking.matchedTerms,
                blocked: blocked,
                tapSafety: tapPolicy.safety,
                tapReason: tapPolicy.reason,
                reason: reason,
                groupKey: groupKey,
                groupLabel: groupLabel,
                groupRequired: groupRequired,
                tapFingerprint: tapFingerprint,
                isSelected: isSelected,
                opensSubflow: opensSubflow
            )
        }
        var seenKeys = Set<String>()
        let deduped = candidates.filter { candidate in
            let key = [candidate.role, normalizedText(candidate.label), candidate.groupKey, candidate.url].joined(separator: "|")
            if seenKeys.contains(key) {
                return false
            }
            seenKeys.insert(key)
            return true
        }
        let limit: Int
        switch pageKind {
        case "dd_item_modal", "dd_storefront", "ue_item_modal", "ue_storefront":
            limit = 40
        case "dd_search_results", "ue_search_results":
            limit = 24
        default:
            limit = 12
        }
        return Array(deduped.sorted { left, right in
            if left.blocked != right.blocked {
                return !left.blocked
            }
            if left.score == right.score {
                return left.label.localizedCaseInsensitiveCompare(right.label) == .orderedAscending
            }
            return left.score > right.score
        }.prefix(limit))
    }

    private static func isBlockedServiceRole(_ role: String) -> Bool {
        ["dd_payment_method", "dd_payment_sheet", "ue_payment_method", "ub_request_cta", "ub_payment_cta"].contains(role)
    }

    private static func displayLabel(label: String, url: String, context: String, role: String) -> String {
        let cleanLabel = label.trimmingCharacters(in: .whitespacesAndNewlines)
        let looksLikeURL = cleanLabel.hasPrefix("http") || cleanLabel.contains("/store/")
        guard cleanLabel.isEmpty || looksLikeURL else {
            return cleanLabel
        }
        let contextTokens = context
            .components(separatedBy: CharacterSet(charactersIn: "|•"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if let useful = contextTokens.first(where: { token in
            let lower = token.lowercased()
            return !lower.contains("delivery fee")
                && !lower.contains("dashpass")
                && !lower.contains("minutes")
                && !lower.contains("reviews")
                && !lower.contains("pickup")
        }) {
            let words = useful.split(separator: " ")
            if !words.isEmpty {
                return words.prefix(role == "store_link" ? 4 : 6).joined(separator: " ")
            }
        }
        return cleanLabel.isEmpty ? url : cleanLabel
    }

    private static func candidateRole(pageKind: String, kind: String, url: String, label: String, context: String) -> String {
        let text = normalizedText([label, context, url].joined(separator: " "))
        let labelText = normalizedText(label)
        if text.contains("skip to main content") || text.contains("accessibility") {
            return "accessibility_link"
        }
        if text.contains("become a dasher") || text.contains("merchant") || text.contains("doordash merchant") || text.contains("gift cards") {
            return "utility_link"
        }
        if text.contains("review") || text.contains("rating") || text.contains("ratings") {
            return "review_link"
        }
        if text.contains("privacy") || text.contains("terms") || text.contains("careers") || text.contains("gift cards") || text.contains("about") || text.contains("help") || text.contains("support") {
            return "utility_link"
        }
        if text.contains("login") || text.contains("sign in") || text.contains("log in") || text.contains("account") {
            return "auth_link"
        }
        if text.contains("checkout") || text.contains("place order") || text.contains("pay now") || text.contains("complete order") {
            return kind == "button" ? "checkout_button" : "checkout_link"
        }
        if text.contains("cart") || text.contains("bag") {
            return kind == "button" ? "cart_button" : "cart_link"
        }
        if pageKind == "menu_or_item" && kind == "link" && (url.contains("#") || text.contains("menu") || text.contains("featured items") || text.contains("specialty pizza") || text.contains("build your own")) && !context.contains("$") {
            return "nav_link"
        }
        if kind == "link" && url.contains("/store/") {
            return "store_link"
        }
        if pageKind == "menu_or_item" {
            if kind == "button" && ["add", "customize", "choose", "select", "continue", "modifier", "topping", "size", "crust"].contains(where: { labelText.contains($0) || text.contains($0) }) {
                return kind == "button" ? "item_action_button" : "menu_item"
            }
            if (label.contains("$") || context.contains("$")) && !text.contains("review") {
                return kind == "button" ? "item_action_button" : "menu_item"
            }
            if kind == "link" {
                return "menu_item"
            }
        }
        if pageKind == "search_results" || pageKind == "web_page" {
            if kind == "link" {
                return "store_link"
            }
        }
        if kind == "button" {
            return "control_button"
        }
        return "generic_candidate"
    }

    private static func roleScoreAdjustment(role: String) -> Double {
        switch role {
        case "store_link":
            return 2.2
        case "dd_store_card":
            return 5.2
        case "ue_store_card":
            return 5.0
        case "ub_pickup_input":
            return 1.0
        case "ub_pickup_result":
            return 4.4
        case "ub_dropoff_input":
            return 1.8
        case "ub_dropoff_result":
            return 4.8
        case "ub_see_prices_cta":
            return 4.5
        case "ub_vehicle_option":
            return 2.4
        case "ub_request_cta":
            return -8.0
        case "menu_item":
            return 1.8
        case "dd_item_card":
            return 3.4
        case "dd_modifier_option":
            return 4.0
        case "dd_modifier_save":
            return 4.2
        case "ue_item_card":
            return 3.2
        case "item_action_button":
            return 1.2
        case "dd_add_to_cart":
            return 4.4
        case "ue_add_to_cart":
            return 4.2
        case "dd_continue_cta":
            return 5.0
        case "ue_continue_cta":
            return 4.8
        case "dd_cart_cta":
            return 3.6
        case "ue_cart_cta":
            return 3.8
        case "dd_tip_option":
            return 2.0
        case "dd_address_cta":
            return 1.0
        case "dd_modal_close":
            return -0.4
        case "ue_continue_browser":
            return 1.4
        case "ue_address_cta":
            return 1.0
        case "ue_address_result":
            return 2.0
        case "ue_search_entry":
            return 1.3
        case "ue_modal_close":
            return -0.4
        case "cart_link", "cart_button":
            return 1.0
        case "control_button":
            return 0.5
        case "review_link":
            return -6.0
        case "nav_link":
            return -3.5
        case "dd_menu_nav":
            return -7.0
        case "accessibility_link":
            return -8.0
        case "utility_link", "auth_link":
            return -4.0
        case "checkout_link", "checkout_button":
            return -1.0
        case "dd_payment_method":
            return -10.0
        default:
            return 0.0
        }
    }

    private static func roleReason(role: String) -> String {
        switch role {
        case "store_link":
            return "Visible store/result candidate"
        case "dd_store_card":
            return "DoorDash merchant card"
        case "ue_store_card":
            return "Uber Eats merchant card"
        case "ub_pickup_input":
            return "Uber pickup field"
        case "ub_pickup_result":
            return "Uber pickup autocomplete result"
        case "ub_dropoff_input":
            return "Uber destination field"
        case "ub_dropoff_result":
            return "Uber destination autocomplete result"
        case "ub_see_prices_cta":
            return "Uber price quote control"
        case "ub_vehicle_option":
            return "Uber vehicle option"
        case "ub_request_cta":
            return "Uber final request button"
        case "menu_item":
            return "Visible menu or item candidate"
        case "dd_item_card":
            return "DoorDash menu item card"
        case "dd_modifier_option":
            return "DoorDash modifier option"
        case "dd_modifier_save":
            return "DoorDash save-options control"
        case "ue_item_card":
            return "Uber Eats menu item card"
        case "item_action_button":
            return "Visible item funnel control"
        case "dd_add_to_cart":
            return "DoorDash add-to-cart control"
        case "ue_add_to_cart":
            return "Uber Eats add-to-order control"
        case "dd_continue_cta":
            return "DoorDash continue-to-checkout control"
        case "ue_continue_cta":
            return "Uber Eats cart-to-checkout control"
        case "dd_cart_cta":
            return "DoorDash cart CTA"
        case "ue_cart_cta":
            return "Uber Eats cart CTA"
        case "dd_tip_option":
            return "DoorDash tip selector"
        case "dd_address_cta":
            return "DoorDash address/edit control"
        case "dd_modal_close":
            return "Dismiss the active sheet if needed"
        case "ue_continue_browser":
            return "Continue in browser gate"
        case "ue_address_cta":
            return "Uber Eats address setup control"
        case "ue_address_result":
            return "Uber Eats address autocomplete result"
        case "ue_search_entry":
            return "Uber Eats search entry"
        case "ue_modal_close":
            return "Dismiss the active Uber Eats sheet"
        case "cart_link", "cart_button":
            return "Visible cart navigation control"
        case "nav_link":
            return "Category/navigation link inside the page"
        case "dd_menu_nav":
            return "DoorDash category navigation"
        case "review_link":
            return "Review content is usually not task-relevant"
        case "accessibility_link":
            return "Accessibility/navigation helper link"
        case "utility_link", "auth_link":
            return "Utility or account navigation"
        default:
            return "Visible candidate with no capsule slot match yet"
        }
    }

    private static func serviceLabelAdjustment(role: String, label: String, context: String) -> Double {
        let text = normalizedText([label, context].joined(separator: " "))
        switch role {
        case "ub_pickup_result":
            if text.contains("allow location access") || text.contains("current location") {
                return 1.4
            }
            return 0.0
        case "ub_dropoff_result":
            if text.contains("stadium") || text.contains("bank") || text.contains("minneapolis") {
                return 0.4
            }
            return 0.0
        case "ub_see_prices_cta":
            return text.contains("see prices") ? 1.2 : 0.0
        case "dd_add_to_cart":
            if text.contains("add to cart") && !text.contains("add item to cart") {
                return 1.4
            }
            if text.contains("add item to cart") {
                return -0.6
            }
            return 0.0
        case "dd_cart_cta":
            if text.contains("view cart") {
                return 1.2
            }
            if text.contains("open cart") || text.contains("open order cart") {
                return 0.2
            }
            return 0.0
        case "dd_store_card":
            if text.contains("domino") || text.contains("pizza") || text.contains("taco") || text.contains("burger") || text.contains("johns") || text.contains("caesars") {
                return 0.5
            }
            return 0.0
        case "dd_modifier_option":
            if text.contains("small") || text.contains("medium") || text.contains("large") || text.contains("meal") || text.contains("drink") || text.contains("fries") || text.contains("size") {
                return 0.9
            }
            return 0.0
        case "dd_modifier_save":
            if text.contains("save options") || text == "save" || text.contains("save") {
                return 1.3
            }
            return 0.0
        case "ue_add_to_cart":
            if text.contains("add to order") {
                return 1.4
            }
            if text.contains("quick add") {
                return -0.2
            }
            return 0.0
        case "ue_cart_cta":
            if text.contains("view cart") || text.contains("view order") {
                return 1.3
            }
            return 0.0
        case "ue_continue_cta":
            if text == "next" || text.contains("go to checkout") {
                return 1.4
            }
            return 0.0
        case "ue_store_card":
            if text.contains("domino") || text.contains("pizza") || text.contains("taco") || text.contains("burger") || text.contains("johns") || text.contains("caesars") {
                return 0.5
            }
            return 0.0
        default:
            return 0.0
        }
    }

    private static func candidateTargets(from capsule: ActionCapsule?) -> [(term: String, weight: Double)] {
        guard let capsule = capsule else {
            return []
        }
        var targets: [(term: String, weight: Double)] = []
        for (key, value) in capsule.slots {
            let cleanValue = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleanValue.isEmpty else {
                continue
            }
            let weight: Double
            switch key {
            case "restaurant", "merchant", "destination":
                weight = 8.0
            case "item", "service_class":
                weight = 2.0
            case "size":
                weight = 1.7
            case "modifiers", "toppings":
                weight = 1.5
            case "add_ons":
                weight = 1.3
            case "service":
                continue
            default:
                weight = 1.0
            }
            let parts: [String]
            if key == "modifiers" || key == "toppings" || key == "add_ons" {
                parts = cleanValue
                    .replacingOccurrences(of: " and ", with: ",")
                    .components(separatedBy: CharacterSet(charactersIn: ",/+&"))
            } else {
                parts = [cleanValue]
            }
            for part in parts {
                let normalized = normalizedText(part)
                if normalized.count > 1 {
                    targets.append((term: normalized, weight: weight))
                }
            }
        }
        return targets
    }

    private static func rankCandidate(_ candidateText: String, targets: [(term: String, weight: Double)]) -> (score: Double, matchedTerms: [String]) {
        let text = normalizedText(candidateText)
        let textTokens = Set(text.split(separator: " ").map(String.init))
        var score = 0.0
        var matches: [String] = []
        for target in targets {
            let variants = targetVariants(for: target.term)
            guard !variants.isEmpty else { continue }
            if variants.contains(where: { text.contains($0) }) {
                score += target.weight
                matches.append(target.term)
                continue
            }
            let targetTokens = variants
                .flatMap { $0.split(separator: " ").map(String.init) }
                .filter { $0.count > 2 }
            guard !targetTokens.isEmpty else { continue }
            let exactTokenMatch = Set(targetTokens).allSatisfy { token in
                textTokens.contains(token)
            }
            if exactTokenMatch {
                score += target.weight * 0.60
                matches.append(target.term)
                continue
            }
            let fuzzyTokenMatch = Set(targetTokens).allSatisfy { token in
                textTokens.contains(where: { candidateToken in
                    fuzzyTokenEqual(token, candidateToken)
                })
            }
            if fuzzyTokenMatch {
                score += target.weight * 0.45
                matches.append(target.term)
            }
        }
        return (score: score, matchedTerms: Array(dictUnique(matches)))
    }

    private static func targetVariants(for term: String) -> [String] {
        guard !term.isEmpty else {
            return []
        }
        var variants = [term]
        let words = term.split(separator: " ").map(String.init)
        if !words.isEmpty {
            let strippedWords = words.map { stripTokenNoise($0) }.filter { !$0.isEmpty }
            if !strippedWords.isEmpty {
                variants.append(strippedWords.joined(separator: " "))
            }
        }
        return Array(dictUnique(variants.map { normalizedText($0) }.filter { !$0.isEmpty }))
    }

    private static func stripTokenNoise(_ token: String) -> String {
        var clean = token
        if clean.hasSuffix("oes") && clean.count > 5 {
            clean = String(clean.dropLast(2))
        }
        if clean.hasSuffix("s") && clean.count > 4 {
            clean.removeLast()
        }
        return clean
    }

    private static func fuzzyTokenEqual(_ left: String, _ right: String) -> Bool {
        if left == right {
            return true
        }
        let normalizedLeft = stripTokenNoise(left)
        let normalizedRight = stripTokenNoise(right)
        if normalizedLeft == normalizedRight {
            return true
        }
        let shorter = normalizedLeft.count <= normalizedRight.count ? normalizedLeft : normalizedRight
        let longer = normalizedLeft.count <= normalizedRight.count ? normalizedRight : normalizedLeft
        if shorter.count >= 5 && longer.hasPrefix(shorter) && (longer.count - shorter.count) <= 2 {
            return true
        }
        return false
    }

    private static func isIrreversibleCandidate(_ candidateText: String) -> Bool {
        let text = normalizedText(candidateText)
        let blockedTerms = [
            "place order",
            "submit order",
            "complete order",
            "purchase",
            "buy now",
            "payment",
            "pay now",
            "confirm order",
            "request uber",
            "request trip",
            "book ride",
            "reserve",
            "send message",
        ]
        return blockedTerms.contains { text.contains($0) }
    }

    private static func buttonTapPolicy(kind: String, url: String, label: String, context: String, blocked: Bool) -> (safety: String, reason: String) {
        guard kind == "button", url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return ("not_applicable", "Link-backed candidates open by URL, not button tap")
        }
        if blocked {
            return ("blocked", "Final or irreversible action language")
        }
        let labelText = normalizedText(label)
        let fullText = normalizedText([label, context].joined(separator: " "))
        let text = labelText.isEmpty ? fullText : labelText
        let blockedTerms = [
            "place order",
            "submit order",
            "complete order",
            "purchase",
            "buy now",
            "payment",
            "pay now",
            "credit debit card",
            "paypal",
            "venmo",
            "cash app pay",
            "klarna",
            "confirm order",
            "request uber",
            "request trip",
            "book ride",
            "reserve",
            "send",
            "delete",
        ]
        if blockedTerms.contains(where: { text.contains($0) }) {
            return ("blocked", "Button label is sensitive")
        }
        let safeTerms = [
            "search",
            "find",
            "go",
            "menu",
            "save",
            "view",
            "filter",
            "apply",
            "show",
            "details",
            "results",
            "load more",
            "see more",
            "continue browsing",
            "close",
            "dismiss",
        ]
        if safeTerms.contains(where: { text.contains($0) }) {
            return ("safe", "Non-final navigation/control button")
        }
        let cautionTerms = [
            "add",
            "add to cart",
            "select",
            "customize",
            "choose",
            "checkout",
            "continue",
            "next",
            "tip",
            "sign in",
            "log in",
            "accept",
        ]
        if cautionTerms.contains(where: { text.contains($0) }) {
            return ("caution", "Needs user review before Memla taps")
        }
        return ("caution", "Unknown button intent")
    }

    private static func normalizedText(_ value: String) -> String {
        value
            .lowercased()
            .replacingOccurrences(of: "\u{2019}", with: "'")
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private static func dictUnique(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.filter { value in
            if seen.contains(value) {
                return false
            }
            seen.insert(value)
            return true
        }
    }

    private static func javaScriptPayloadError(_ payload: [String: Any]) -> String? {
        let message = stringValue(payload["memla_js_error"])
        guard !message.isEmpty else {
            return nil
        }
        let script = stringValue(payload["memla_js_script"])
        let stack = stringValue(payload["memla_js_stack"])
        let firstStackLine = stack
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .first ?? ""
        if !script.isEmpty, !firstStackLine.isEmpty {
            return "\(script): \(message) [\(firstStackLine)]"
        }
        if !script.isEmpty {
            return "\(script): \(message)"
        }
        return message
    }

    private static func javascriptStringLiteral(_ value: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: [value], options: []),
              let encodedArray = String(data: data, encoding: .utf8),
              encodedArray.hasPrefix("["),
              encodedArray.hasSuffix("]") else {
            return "\"\""
        }
        return String(encodedArray.dropFirst().dropLast())
    }

    private static func searchFillScript(query: String, submit: Bool) -> String {
        let queryLiteral = javascriptStringLiteral(query)
        let submitLiteral = submit ? "true" : "false"
        return """
        (() => {
          const query = \(queryLiteral);
          const shouldSubmit = \(submitLiteral);
          const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const visible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 1 && rect.height > 1;
          };
          const labelFor = (el) => clean([
            el.getAttribute('aria-label'),
            el.getAttribute('placeholder'),
            el.getAttribute('name'),
            el.getAttribute('id'),
            el.getAttribute('type'),
            el.getAttribute('title')
          ].join(' ')).toLowerCase();
          const fields = Array.from(document.querySelectorAll('input,textarea'))
            .filter(visible)
            .filter((el) => {
              const type = (el.getAttribute('type') || '').toLowerCase();
              return !['hidden', 'password', 'checkbox', 'radio', 'file'].includes(type);
            });
          const target = fields.find((el) => {
            const type = (el.getAttribute('type') || '').toLowerCase();
            const label = labelFor(el);
            return type === 'search'
              || label.includes('search')
              || label.includes('restaurant')
              || label.includes('store')
              || label.includes('food')
              || label.includes('address')
              || label.includes('delivery')
              || label.includes('location');
          }) || fields[0];
          if (!target) {
            return { ok: false, reason: 'search_input_not_found' };
          }
          target.focus();
          const valueSetter = Object.getOwnPropertyDescriptor(
            target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype,
            'value'
          )?.set;
          if (valueSetter) {
            valueSetter.call(target, query);
          } else {
            target.value = query;
          }
          try {
            target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: query }));
          } catch (_) {
            target.dispatchEvent(new Event('input', { bubbles: true }));
          }
          target.dispatchEvent(new Event('change', { bubbles: true }));
          if (!shouldSubmit) {
            return { ok: true, reason: 'filled_search_query', query };
          }
          const buttons = Array.from(document.querySelectorAll('button,input[type="submit"],[role="button"]'))
            .filter(visible);
          const searchButton = buttons.find((el) => /search|find|go|submit/i.test(clean([el.innerText, el.value, el.getAttribute('aria-label'), el.getAttribute('title')].join(' '))));
          if (searchButton && typeof searchButton.click === 'function') {
            searchButton.click();
            return { ok: true, reason: 'filled_and_clicked_search', query };
          }
          target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          target.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          if (target.form && typeof target.form.requestSubmit === 'function') {
            target.form.requestSubmit();
            return { ok: true, reason: 'filled_and_submitted_search', query };
          }
          return { ok: true, reason: 'filled_search_query_enter_sent', query };
        })();
        """
    }

    private static func uberRideLocationFillScript(query: String, isPickup: Bool) -> String {
        let queryLiteral = javascriptStringLiteral(query)
        let selector = isPickup
            ? "input[data-testid=\"dotcom-ui.pickup-destination.input.pickup\"]"
            : "input[data-testid=\"dotcom-ui.pickup-destination.input.destination.drop0\"]"
        let reason = isPickup ? "filled_uber_pickup" : "filled_uber_destination"
        return """
        (() => {
          const query = \(queryLiteral);
          const target = document.querySelector('\(selector)');
          if (!target) {
            return { ok: false, reason: 'uber_ride_input_not_found' };
          }
          target.scrollIntoView({ block: 'center', inline: 'center' });
          if (typeof target.click === 'function') {
            target.click();
          }
          if (typeof target.focus === 'function') {
            target.focus();
          }
          const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
          if (valueSetter) {
            valueSetter.call(target, query);
          } else {
            target.value = query;
          }
          try {
            target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: query }));
          } catch (_) {
            target.dispatchEvent(new Event('input', { bubbles: true }));
          }
          target.dispatchEvent(new Event('change', { bubbles: true }));
          return { ok: true, reason: '\(reason)', query };
        })();
        """
    }

    private static func uberRideFieldFocusScript(isPickup: Bool) -> String {
        if isPickup {
            return """
            (() => {
              const input = document.querySelector('input[aria-label="Pickup location needs to be filled in"]')
                || document.querySelector('input[data-testid="dotcom-ui.pickup-destination.input.pickup"]');

              if (!input) {
                return { ok: false, reason: 'uber_pickup_input_not_found' };
              }

              try { input.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
              if (typeof input.focus === 'function') {
                try { input.focus({ preventScroll: true }); } catch (_) {
                  try { input.focus(); } catch (_) {}
                }
              }
              try { input.click(); } catch (_) {}

              try { input.dispatchEvent(new FocusEvent('focus', { bubbles: true })); } catch (_) {}
              try { input.dispatchEvent(new FocusEvent('focusin', { bubbles: true })); } catch (_) {}
              try { input.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window })); } catch (_) {}
              try { input.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window })); } catch (_) {}
              try { input.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); } catch (_) {}

              return { ok: true, reason: 'focused_uber_pickup_field' };
            })();
            """
        }
        let selector = isPickup
            ? "input[data-testid=\"dotcom-ui.pickup-destination.input.pickup\"]"
            : "input[data-testid=\"dotcom-ui.pickup-destination.input.destination.drop0\"]"
        let wrapperSelector = isPickup
            ? "div[data-testid=\"dotcom-ui.pickup-destination.placeholder.pickup\"]"
            : "div[data-testid=\"dotcom-ui.pickup-destination.placeholder.destination.drop0\"]"
        let reason = isPickup ? "focused_uber_pickup_field" : "focused_uber_destination_field"
        return """
        (() => {
          const target = document.querySelector('\(selector)');
          const wrapper = document.querySelector('\(wrapperSelector)') || target?.closest('[data-tracking="disabled"]');
          const explicitRow = target?.closest('[data-testid="pudo-select-v2"]');
          const findInteractiveRow = (node) => {
            let current = node;
            while (current && current !== document.body) {
              try {
                const rect = typeof current.getBoundingClientRect === 'function'
                  ? current.getBoundingClientRect()
                  : { width: 0, height: 0 };
                if (current.getAttribute('data-testid') === 'pudo-select-v2') {
                  return current;
                }
                if (current.querySelector('\(selector)') && rect.width > 200 && rect.height >= 40) {
                  return current;
                }
              } catch (_) {}
              current = current.parentElement;
            }
            return null;
          };
          const row = explicitRow || findInteractiveRow(target) || wrapper?.closest('[data-testid="pudo-select-v2"]') || wrapper?.parentElement || wrapper;
          const activate = (node) => {
            if (!node) return;
            try { node.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
            ['mousedown', 'mouseup', 'click'].forEach((type) => {
              try {
                node.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
              } catch (_) {}
            });
            if (typeof node.click === 'function') {
              try { node.click(); } catch (_) {}
            }
          };
          if (!target) {
            return { ok: false, reason: 'uber_ride_input_not_found' };
          }
          activate(row);
          activate(wrapper);
          activate(target);
          if (typeof target.focus === 'function') {
            try { target.focus(); } catch (_) {}
          }
          return { ok: true, reason: '\(reason)' };
        })();
        """
    }

    private static func buttonTapScript(domIndex: Int, allowCaution: Bool) -> String {
        let allowCautionLiteral = allowCaution ? "true" : "false"
        return """
        (() => {
          const targetIndex = \(domIndex);
          const allowCaution = \(allowCautionLiteral);
          const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const normalized = (value) => clean(value).toLowerCase().replace(/[^a-z0-9]+/g, ' ');
          const visible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 1 && rect.height > 1;
          };
          const isTextInput = (el) => {
            if (!el) return false;
            const tag = (el.tagName || '').toLowerCase();
            if (tag === 'textarea' || tag === 'select') return true;
            if (tag !== 'input') return false;
            const type = (el.getAttribute('type') || '').toLowerCase();
            return !['hidden', 'password', 'checkbox', 'radio', 'file', 'submit', 'button'].includes(type);
          };
          const elements = Array.from(document.querySelectorAll('a[href],button,[role="button"],[role="option"],input,textarea,select,input[type="button"],input[type="submit"]'))
            .filter(visible);
          const target = elements[targetIndex];
          if (!target) {
            return { ok: false, reason: 'button_candidate_not_found' };
          }
          if (target.matches('a[href]')) {
            return { ok: false, reason: 'link_candidate_not_tapped' };
          }
          if (isTextInput(target)) {
            target.scrollIntoView({ block: 'center', inline: 'center' });
            if (typeof target.click === 'function') {
              target.click();
            }
            if (typeof target.focus === 'function') {
              target.focus();
            }
            return { ok: true, reason: 'focused_input_candidate', label: clean(target.getAttribute('aria-label') || target.getAttribute('placeholder') || target.getAttribute('name') || target.id) };
          }
          const label = clean(target.innerText || target.value || target.getAttribute('aria-label') || target.getAttribute('title'));
          const context = clean(target.closest('article,li,section,div')?.innerText || '');
          const labelText = normalized(label);
          const text = normalized([label, context].join(' '));
          const sensitiveText = labelText || text;
          const blockedTerms = [
            'place order',
            'submit order',
            'complete order',
            'purchase',
            'buy now',
            'payment',
            'pay now',
            'confirm order',
            'book ride',
            'reserve',
            'send',
            'delete'
          ];
          if (blockedTerms.some((term) => sensitiveText.includes(term))) {
            return { ok: false, reason: 'sensitive_button_blocked', label };
          }
          const safeTerms = [
            'search',
            'find',
            'go',
            'menu',
            'save',
            'view',
            'filter',
            'apply',
            'show',
            'details',
            'results',
            'load more',
            'see more',
            'continue browsing',
            'close',
            'dismiss'
          ];
          if (!safeTerms.some((term) => text.includes(term))) {
            if (!allowCaution) {
              return { ok: false, reason: 'button_not_policy_safe', label };
            }
            target.scrollIntoView({ block: 'center', inline: 'center' });
            target.click();
            return { ok: true, reason: 'tapped_reviewed_button', label };
          }
          target.scrollIntoView({ block: 'center', inline: 'center' });
          target.click();
          return { ok: true, reason: 'tapped_safe_button', label };
        })();
        """
    }

    private static func doorDashModifierOptionTapScript(
        label: String,
        groupKey: String,
        groupLabel: String,
        tapFingerprint: String
    ) -> String {
        let labelLiteral = javaScriptStringLiteral(label)
        let groupKeyLiteral = javaScriptStringLiteral(groupKey)
        let groupLabelLiteral = javaScriptStringLiteral(groupLabel)
        let fingerprintLiteral = javaScriptStringLiteral(tapFingerprint)
        return """
        (() => {
          try {
          const targetLabel = \(labelLiteral);
          const targetGroupKey = \(groupKeyLiteral);
          const targetGroupLabel = \(groupLabelLiteral);
          const targetFingerprint = \(fingerprintLiteral);
          const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const normalized = (value) => clean(value).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
          const rawLines = (el) => String(el?.innerText || '')
            .split('\\n')
            .map(clean)
            .filter(Boolean);
          const firstMeaningfulTextLine = (el) => {
            const lines = rawLines(el);
            return lines.find((line) => {
              const lower = line.toLowerCase();
              return /[a-z]/i.test(line)
                && !/^(required|optional|preferences|choose your size|topping side|user preferences)$/i.test(lower)
                && !/\\$\\d/.test(lower);
            }) || lines[0] || '';
          };
          const visible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 1 && rect.height > 1;
          };
          const itemModal = Array.from(document.querySelectorAll('[data-testid="ItemModal"], [role="dialog"]'))
            .filter(visible)[0];
          if (!itemModal) {
            return { ok: false, reason: 'doordash_item_modal_not_found' };
          }

          const inferGroupKey = (header, text = '') => {
            const combined = clean([header, text].join(' ')).toLowerCase();
            if (!combined) return 'unknown';
            if (/choose your size|\\bsize\\b|\\b10"\\b|\\b12"\\b|\\b14"\\b|\\b16"\\b/.test(combined)) return 'size';
            if (/topping side|left half|right half|whole/.test(combined)) return 'topping_side';
            if (/\\bcrust\\b|hand tossed|thin crust|brooklyn|gluten free/.test(combined)) return 'crust';
            if (/topping|premium chicken|pineapple|pepperoni|beef|ham|bacon|olive|mushroom|onion|sausage/.test(combined)) return 'topping';
            if (/preferences|special instructions/.test(combined)) return 'preferences';
            return 'unknown';
          };

          const optionRootForElement = (el) => {
            if (!el) return null;
            const id = clean((el.getAttribute && el.getAttribute('id')) || '');
            if (id) {
              try {
                const boundLabel = itemModal.querySelector(`label[for="${CSS.escape(id)}"]`);
                if (boundLabel && visible(boundLabel)) {
                  return boundLabel;
                }
              } catch (_) {}
            }
            return el.closest('label,[role="radio"],[role="checkbox"]') || el;
          };
          const controlForOption = (el, root) => {
            if (el && el.matches && el.matches('input[type="radio"],input[type="checkbox"]')) {
              return el;
            }
            const rootNode = root || el;
            if (rootNode && rootNode.querySelector) {
              const descendant = rootNode.querySelector('input[type="radio"],input[type="checkbox"]');
              if (descendant) {
                return descendant;
              }
            }
            const id = clean((rootNode && rootNode.getAttribute && rootNode.getAttribute('for')) || '');
            if (id) {
              try {
                const escaped = window.CSS && CSS.escape ? CSS.escape(id) : id;
                const bySelector = itemModal.querySelector(`#${escaped}`);
                if (bySelector) {
                  return bySelector;
                }
              } catch (_) {}
              const byId = document.getElementById(id);
              if (byId) {
                return byId;
              }
            }
            return null;
          };
          const checkedStateForOption = (el, root) => {
            const nodes = [el, root].filter(Boolean);
            for (const node of nodes) {
              const ariaChecked = clean((node.getAttribute && node.getAttribute('aria-checked')) || '').toLowerCase();
              if (ariaChecked === 'true') {
                return true;
              }
              if (node.matches && node.matches('input[type="radio"],input[type="checkbox"]') && node.checked) {
                return true;
              }
              const checkedDescendant = node.querySelector
                ? node.querySelector('input[type="radio"]:checked,input[type="checkbox"]:checked,[role="radio"][aria-checked="true"],[role="checkbox"][aria-checked="true"]')
                : null;
              if (checkedDescendant) {
                return true;
              }
            }
            return false;
          };

          const optionGroupCache = new WeakMap();
          const groupDescriptorForNode = (node) => {
            if (!node || !visible(node)) return null;
            const text = clean(node.textContent || '');
            if (!text || text.length < 12 || text.length > 900) return null;
            if (/^your recommended options\\b/i.test(text)) return null;
            if (!/(required|optional).*(select|choose)|preferences\\s*\\(optional\\)|choose your|topping side|crust|toppings?/i.test(text)) return null;
            const headerNode = node.querySelector('h1,h2,h3,h4,[role="heading"]');
            const heading = clean(headerNode?.textContent || '');
            const firstLine = clean((text.split('\\n').find(Boolean)) || '');
            const hasStructuredMarker = /(required|optional).*(select|choose)|preferences\\s*\\(optional\\)|choose your|add toppings|crust seasoning|topping side/i.test(text);
            const optionDescendants = Array.from(
              node.querySelectorAll('label,input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]')
            ).filter(visible);
            if (!heading && !hasStructuredMarker && optionDescendants.length < 2) return null;
            if (!heading && !hasStructuredMarker && optionDescendants.length <= 1 && /edit selection/i.test(text)) return null;
            const source = heading || text;
            const headerMatch = source.match(/^(.{1,120}?)(?:\\s+(?:Required|\\(Optional\\)|Optional)\\b)/i);
            const header = clean(
              headerMatch
                ? headerMatch[1]
                : (/^preferences\\b/i.test(source) ? 'Preferences' : heading || firstLine)
            );
            if (!header || /^required$/i.test(header) || /^optional$/i.test(header)) return null;
            return {
              header,
              groupKey: inferGroupKey(header, text),
              root: node,
              text
            };
          };

          const groupForRoot = (root) => {
            if (!root) return null;
            if (optionGroupCache.has(root)) {
              return optionGroupCache.get(root);
            }
            let node = root;
            let group = null;
            for (let depth = 0; node && node !== itemModal && depth < 8; depth += 1, node = node.parentElement) {
              group = groupDescriptorForNode(node);
              if (group) {
                break;
              }
            }
            optionGroupCache.set(root, group);
            return group;
          };
          const opensSubflowForOptionRoot = (root) => {
            if (!root || !root.querySelectorAll) return false;
            return Array.from(root.querySelectorAll('svg path')).some((path) => {
              const d = clean(path.getAttribute('d') || '');
              return d.includes('11.707 7.29289') || d.includes('9.58586 7.99992');
            });
          };

          const fingerprintFor = (role, label, groupKey, groupLabel) =>
            clean([role, groupKey, groupLabel, label].join(' | ')).toLowerCase();

          const optionElements = Array.from(itemModal.querySelectorAll('label,input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]'))
            .filter(visible);

          const scored = optionElements.map((el) => {
            const root = optionRootForElement(el);
            if (!root || !visible(root)) return null;
            const control = controlForOption(el, root);
            const resolvedLabel = firstMeaningfulTextLine(root) || clean((el.getAttribute ? el.getAttribute('aria-label') : '') || el.innerText || el.textContent || '');
            if (!resolvedLabel) return null;
            const group = groupForRoot(root);
            const resolvedGroupLabel = clean(group?.header || '');
            const resolvedGroupKey = clean(group?.groupKey || inferGroupKey(resolvedGroupLabel, resolvedLabel));
            const fingerprint = fingerprintFor('dd_modifier_option', resolvedLabel, resolvedGroupKey, resolvedGroupLabel);
            const isSelected = checkedStateForOption(control || el, root);
            const opensSubflow = opensSubflowForOptionRoot(root);
            let score = 0;
            const normalizedLabel = normalized(resolvedLabel);
            const normalizedTarget = normalized(targetLabel);
            if (normalizedLabel === normalizedTarget) score += 120;
            else if (normalizedLabel.includes(normalizedTarget) || normalizedTarget.includes(normalizedLabel)) score += 80;
            if (targetGroupKey && resolvedGroupKey === targetGroupKey) score += 110;
            if (targetGroupLabel && normalized(resolvedGroupLabel) === normalized(targetGroupLabel)) score += 70;
            if (targetFingerprint && fingerprint === normalized(targetFingerprint)) score += 180;
            return { el, root, control, resolvedLabel, resolvedGroupKey, resolvedGroupLabel, fingerprint, isSelected, opensSubflow, score };
          }).filter(Boolean).sort((left, right) => right.score - left.score);

          const best = scored.find((item) => item.score >= 120);
          if (!best) {
            return { ok: false, reason: 'doordash_modifier_option_not_found' };
          }
          if (best.isSelected && !best.opensSubflow) {
            return {
              ok: true,
              reason: 'doordash_modifier_already_selected',
              label: best.resolvedLabel,
              group_key: best.resolvedGroupKey,
              group_label: best.resolvedGroupLabel
            };
          }

          const activate = (node) => {
            if (!node) return;
            try { node.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
            const rect = typeof node.getBoundingClientRect === 'function'
              ? node.getBoundingClientRect()
              : { left: 0, top: 0, width: 0, height: 0 };
            const pointInit = {
              bubbles: true,
              cancelable: true,
              composed: true,
              clientX: rect.left + rect.width / 2,
              clientY: rect.top + rect.height / 2
            };
            if (typeof node.focus === 'function') {
              try { node.focus(); } catch (_) {}
            }
            ['mousedown', 'mouseup', 'click'].forEach((type) => {
              try {
                node.dispatchEvent(new MouseEvent(type, {
                  bubbles: pointInit.bubbles,
                  cancelable: pointInit.cancelable,
                  composed: pointInit.composed,
                  clientX: pointInit.clientX,
                  clientY: pointInit.clientY,
                  view: window
                }));
              } catch (_) {}
            });
            if (typeof node.click === 'function') {
              try { node.click(); } catch (_) {}
            }
          };

          const primaryTarget = best.opensSubflow
            ? (best.root || best.el || best.control)
            : (best.control || best.root || best.el);
          const fallbackTarget = best.opensSubflow
            ? (best.control && best.control !== primaryTarget ? best.control : best.el)
            : (best.root && best.root !== primaryTarget ? best.root : best.el);
          activate(primaryTarget);
          let selectedAfterTap = checkedStateForOption(best.control || best.el, best.root);
          if (!selectedAfterTap && fallbackTarget && fallbackTarget !== primaryTarget) {
            activate(fallbackTarget);
            selectedAfterTap = checkedStateForOption(best.control || best.el, best.root);
          }
          return {
            ok: true,
            reason: 'tapped_doordash_modifier_option',
            label: best.resolvedLabel,
            group_key: best.resolvedGroupKey,
            group_label: best.resolvedGroupLabel,
            selected_after_tap: selectedAfterTap
          };
          } catch (error) {
            return {
              ok: false,
              reason: 'memla_js_exception',
              memla_js_script: 'dd_modifier_option_tap',
              memla_js_error: String(error),
              memla_js_stack: String((error && error.stack) || '')
            };
          }
        })();
        """
    }

    private static let doorDashModifierSaveScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const itemModal = Array.from(document.querySelectorAll('[data-testid="ItemModal"], [role="dialog"]'))
        .filter(visible)[0] || document;
      const saveMatcher = (el) => {
        const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
        return /^save(?: options)?(?:\\s*\\+\\$?\\d[\\d.,]*)?$/i.test(text) || /^save$/i.test(text);
      };
      const button = Array.from(document.querySelectorAll('#prism-modal-footer button[data-testid="optionFooter"], [data-testid="in-content-modal-footer-container"] button[data-testid="optionFooter"], button[data-testid="optionFooter"]'))
        .filter(visible)
        .find(saveMatcher)
        || Array.from(document.querySelectorAll('button, [role="button"]'))
          .filter(visible)
          .find((el) => saveMatcher(el) && (itemModal.contains(el) || el.closest('#prism-modal-footer, .ModalFooter-sc-ibg5mu-5, [data-testid="in-content-modal-footer-container"]')));
      if (!button) {
        return { ok: false, reason: 'doordash_modifier_save_not_found' };
      }
      const footer = button.closest('#prism-modal-footer, [data-testid="in-content-modal-footer-container"], .ModalFooter-sc-ibg5mu-5, section, div');
      const activate = (node) => {
        if (!node) return;
        try { node.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
        const rect = typeof node.getBoundingClientRect === 'function'
          ? node.getBoundingClientRect()
          : { left: 0, top: 0, width: 0, height: 0 };
        const pointInit = {
          bubbles: true,
          cancelable: true,
          composed: true,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2
        };
        if (typeof node.focus === 'function') {
          try { node.focus(); } catch (_) {}
        }
        ['mousedown', 'mouseup', 'click'].forEach((type) => {
          try {
            node.dispatchEvent(new MouseEvent(type, {
              bubbles: pointInit.bubbles,
              cancelable: pointInit.cancelable,
              composed: pointInit.composed,
              clientX: pointInit.clientX,
              clientY: pointInit.clientY,
              view: window
            }));
          } catch (_) {}
        });
        if (typeof node.click === 'function') {
          try { node.click(); } catch (_) {}
        }
      };
      activate(footer);
      activate(button);
      return { ok: true, reason: 'tapped_doordash_modifier_save', label: clean(button.innerText || button.textContent || '') };
      } catch (error) {
        return {
          ok: false,
          reason: 'memla_js_exception',
          memla_js_script: 'dd_modifier_save_tap',
          memla_js_error: String(error),
          memla_js_stack: String((error && error.stack) || '')
        };
      }
    })();
    """

    private static let doorDashAddToCartScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const addMatcher = (el) => {
        const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
        return /^(?:add to cart|update item)(?:\\s*[-+]\\s*.*)?$/i.test(text) || /add to cart|update item/i.test(text);
      };
      const button = Array.from(document.querySelectorAll(
        '#prism-modal-footer button[data-testid="optionFooter"], [data-testid="in-content-modal-footer-container"] button[data-testid="optionFooter"], button[data-testid="optionFooter"], button, [role="button"]'
      ))
        .filter(visible)
        .find(addMatcher);
      if (!button) {
        return { ok: false, reason: 'doordash_add_to_cart_not_found' };
      }
      const footer = button.closest('#prism-modal-footer, [data-testid="in-content-modal-footer-container"], .ModalFooter-sc-ibg5mu-5, section, div');
      const activate = (node) => {
        if (!node) return;
        try { node.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
        const rect = typeof node.getBoundingClientRect === 'function'
          ? node.getBoundingClientRect()
          : { left: 0, top: 0, width: 0, height: 0 };
        const pointInit = {
          bubbles: true,
          cancelable: true,
          composed: true,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2
        };
        if (typeof node.focus === 'function') {
          try { node.focus(); } catch (_) {}
        }
        ['mousedown', 'mouseup', 'click'].forEach((type) => {
          try {
            node.dispatchEvent(new MouseEvent(type, {
              bubbles: pointInit.bubbles,
              cancelable: pointInit.cancelable,
              composed: pointInit.composed,
              clientX: pointInit.clientX,
              clientY: pointInit.clientY,
              view: window
            }));
          } catch (_) {}
        });
        if (typeof node.click === 'function') {
          try { node.click(); } catch (_) {}
        }
      };
      activate(footer);
      activate(button);
      return { ok: true, reason: 'tapped_doordash_add_to_cart', label: clean(button.innerText || button.textContent || '') };
      } catch (error) {
        return {
          ok: false,
          reason: 'memla_js_exception',
          memla_js_script: 'dd_add_to_cart_tap',
          memla_js_error: String(error),
          memla_js_stack: String((error && error.stack) || '')
        };
      }
    })();
    """

    private static let doorDashContinueToCheckoutScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const labelForElement = (el) => clean(el?.innerText || el?.textContent || el?.value || el?.getAttribute?.('aria-label') || el?.getAttribute?.('title') || '');
      const contextForElement = (el, rootOverride) => clean((rootOverride || el?.closest('article,li,section,div,[role="dialog"]'))?.textContent || '').slice(0, 420);
      const ancestorSet = (el) => {
        const nodes = new Set();
        let node = el;
        while (node) {
          nodes.add(node);
          node = node.parentElement;
        }
        return nodes;
      };
      const sharedAncestor = (left, right) => {
        if (!left && !right) return null;
        if (!left) return right?.closest('section,div,[role="dialog"]') || right || null;
        if (!right) return left?.closest('section,div,[role="dialog"]') || left || null;
        const leftAncestors = ancestorSet(left);
        let node = right;
        while (node) {
          if (leftAncestors.has(node)) {
            return node;
          }
          node = node.parentElement;
        }
        return left.closest('section,div,[role="dialog"]') || right.closest('section,div,[role="dialog"]') || left;
      };
      const continueMatcher = (el, root) => {
        const text = clean([labelForElement(el), contextForElement(el, root)].join(' ')).toLowerCase();
        if (!text) return false;
        if (/close|dismiss|address|clear view ct|edit address|continue browsing|open cart|view cart/.test(text)) return false;
        return /continue|checkout|review order/.test(text);
      };
      const activate = (node) => {
        if (!node) return;
        try { node.scrollIntoView({ block: 'center', inline: 'center' }); } catch (_) {}
        const rect = typeof node.getBoundingClientRect === 'function'
          ? node.getBoundingClientRect()
          : { left: 0, top: 0, width: 0, height: 0 };
        const pointInit = {
          bubbles: true,
          cancelable: true,
          composed: true,
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2
        };
        if (typeof node.focus === 'function') {
          try { node.focus(); } catch (_) {}
        }
        ['mousedown', 'mouseup', 'click'].forEach((type) => {
          try {
            node.dispatchEvent(new MouseEvent(type, {
              bubbles: pointInit.bubbles,
              cancelable: pointInit.cancelable,
              composed: pointInit.composed,
              clientX: pointInit.clientX,
              clientY: pointInit.clientY,
              view: window
            }));
          } catch (_) {}
        });
        if (typeof node.click === 'function') {
          try { node.click(); } catch (_) {}
        }
      };

      const controls = Array.from(document.querySelectorAll('button,[role="button"],a[href]')).filter(visible);
      const exactCheckoutAnchor = (() => {
        try {
          const match = document.evaluate(
            '//a[contains(@href, "/consumer/checkout/") and contains(@class, "ButtonRoot")]',
            document,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
            null
          ).singleNodeValue;
          return visible(match) ? match : null;
        } catch (_) {
          return null;
        }
      })();
      const continueAnchor = exactCheckoutAnchor
        || controls.find((el) =>
          el.matches('a[href*="/consumer/checkout"]') && continueMatcher(el, null)
        )
        || null;
      const cartCloseButton = controls.find((el) => /close/i.test(labelForElement(el))) || null;
      const visibleDialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]')).filter(visible);
      const cartDrawer = sharedAncestor(continueAnchor, cartCloseButton)
        || visibleDialogs.find((el) => Array.from(el.querySelectorAll('button,[role="button"],a[href]')).filter(visible).some((child) => continueMatcher(child, el)))
        || null;

      const scopedControls = cartDrawer
        ? Array.from(cartDrawer.querySelectorAll('button,[role="button"],a[href]')).filter(visible)
        : controls;
      const continueControl = scopedControls.find((el) => continueMatcher(el, cartDrawer || null))
        || controls.find((el) => continueMatcher(el, cartDrawer || null))
        || null;
      const resolvedContinue = continueAnchor || continueControl;
      if (!resolvedContinue) {
        return { ok: false, reason: 'doordash_continue_not_found' };
      }

      activate(resolvedContinue);
      return {
        ok: true,
        reason: 'tapped_doordash_continue',
        label: clean(labelForElement(resolvedContinue) || 'Continue')
      };
      } catch (error) {
        return {
          ok: false,
          reason: 'memla_js_exception',
          memla_js_script: 'dd_continue_tap',
          memla_js_error: String(error),
          memla_js_stack: String((error && error.stack) || '')
        };
      }
    })();
    """

    private static let pageInspectionScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const absoluteHref = (el) => {
        const rawHref = el?.getAttribute?.('href') || '';
        try {
          return rawHref ? new URL(rawHref, location.href).href : '';
        } catch (_) {
          return rawHref;
        }
      };
      const interactiveElements = Array.from(document.querySelectorAll('a[href],button,[role="button"],[role="option"],input,textarea,select,input[type="button"],input[type="submit"]'))
        .filter(visible);
      interactiveElements.forEach((el, index) => {
        try {
          el.dataset.memlaIndex = String(index);
        } catch (_) {}
      });
      const elementIndex = (el) => Number(el?.dataset?.memlaIndex ?? interactiveElements.indexOf(el));
      const labelForElement = (el) => clean(el?.innerText || el?.textContent || el?.value || el?.getAttribute?.('aria-label') || el?.getAttribute?.('title') || absoluteHref(el));
      const contextForElement = (el, rootOverride) => clean((rootOverride || el.closest('article,li,section,div,[role="dialog"]'))?.textContent || '').slice(0, 420);
      const candidateFromElement = (el, role, rootOverride, overrideLabel, metadata = {}) => ({
        id: String(elementIndex(el)),
        kind: el.matches('a[href]') ? 'link' : 'button',
        label: clean(overrideLabel || labelForElement(el)),
        url: absoluteHref(el),
        context: contextForElement(el, rootOverride),
        service_role: role,
        group_key: clean(metadata.groupKey || ''),
        group_label: clean(metadata.groupLabel || ''),
        group_required: metadata.groupRequired ? 'true' : 'false',
        tap_fingerprint: clean(metadata.tapFingerprint || ''),
        selected: metadata.selected ? 'true' : 'false',
        opens_subflow: metadata.opensSubflow ? 'true' : 'false'
      });
      const collectText = (selector, limit, mapper, root = document) => Array.from(root.querySelectorAll(selector))
        .filter(visible)
        .map(mapper)
        .map(clean)
        .filter(Boolean)
        .slice(0, limit);

      const headings = collectText('h1,h2,h3,[role="heading"]', 10, (el) => el.innerText || el.textContent);
      const inputs = collectText('input,textarea,select', 18, (el) => el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || el.id || el.type || el.tagName);
      const buttons = collectText('button,[role="button"],input[type="button"],input[type="submit"],a[role="button"]', 24, (el) => el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title'));
      const links = collectText('a[href]', 24, (el) => el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || el.href);
      const candidates = interactiveElements
        .map((el) => {
          return {
            id: String(elementIndex(el)),
            kind: el.matches('a[href]') ? 'link' : 'button',
            label: labelForElement(el),
            url: absoluteHref(el),
            context: contextForElement(el)
          };
        })
        .filter((candidate) => candidate.label || candidate.url)
        .slice(0, 40);

      let doordashCandidates = [];
      let doordashActiveLayer = 'page';
      let doordashModalTitle = '';
      let doordashStoreCardCount = 0;
      let doordashItemCardCount = 0;
      let doordashTipOptionCount = 0;
      let doordashCustomizerGroupCount = 0;
      let doordashCustomizerRequiredGroupCount = 0;
      let doordashCustomizerOptionCount = 0;
      let doordashCustomizerCheckedRadioCount = 0;
      let doordashCustomizerCheckedCheckboxCount = 0;
      let doordashCustomizerRecommendedPresetCount = 0;
      let doordashCustomizerHasSpecialInstructions = false;
      let doordashCustomizerAddToCartLabel = '';
      let doordashCustomizerActiveGroupKey = '';
      let doordashCustomizerActiveGroupLabel = '';
      let doordashCustomizerActiveGroupRequired = false;
      let doordashHasCartCTA = false;
      let doordashHasContinueCTA = false;
      let doordashHasAddToCartCTA = false;
      let doordashHasAddressCTA = false;
      let doordashHasPaymentSheet = false;
      let doordashHasCartCloseCTA = false;
      let doordashActiveRoot = null;
      let ubereatsCandidates = [];
      let ubereatsActiveLayer = 'page';
      let ubereatsModalTitle = '';
      let ubereatsStoreCardCount = 0;
      let ubereatsItemCardCount = 0;
      let ubereatsHasCartCTA = false;
      let ubereatsHasContinueCTA = false;
      let ubereatsHasAddToCartCTA = false;
      let ubereatsHasAddressGate = false;
      let ubereatsHasContinueBrowser = false;
      let ubereatsHasSearchEntry = false;
      let uberCandidates = [];
      let uberActiveLayer = 'page';
      let uberPickupValue = '';
      let uberDropoffValue = '';
      let uberPickupMissing = false;
      let uberDropoffMissing = false;
      let uberPickupResultCount = 0;
      let uberDropoffResultCount = 0;
      let uberVehicleOptionCount = 0;
      let uberHasPickupInput = false;
      let uberHasDropoffInput = false;
      let uberHasSeePricesCTA = false;
      let uberHasRequestCTA = false;

      if (/doordash\\.com$/i.test(location.hostname)) {
        const pushUnique = (collection, candidate) => {
          if (!candidate || (!candidate.label && !candidate.url)) return;
          const key = [candidate.service_role || '', candidate.label || '', candidate.url || '', candidate.id || ''].join('|');
          if (collection.some((existing) => [existing.service_role || '', existing.label || '', existing.url || '', existing.id || ''].join('|') === key)) {
            return;
          }
          collection.push(candidate);
        };
        const rawLines = (el) => String(el?.innerText || '')
          .split('\\n')
          .map(clean)
          .filter(Boolean);
        const firstMeaningfulTextLine = (el) => {
          const lines = rawLines(el);
          return lines.find((line) => {
            const lower = line.toLowerCase();
            return /[a-z]/i.test(line)
              && !/^(get to know us|let us help you|doing business|welcome back!?|convenience & drugstores|deals & benefits|featured items|most ordered|restaurant|grocery|all)$/i.test(lower)
              && !/lower fees|delivery fee|dashpass|pickup|minutes|mins| mi\\b|\\bmin\\b|reviews?|\\(\\d\\+\\)/i.test(lower);
          }) || lines[0] || '';
        };
        const closestWithText = (el, minLength = 20, maxLength = 260) => {
          let node = el;
          let fallback = el;
          while (node && node !== document.body) {
            const length = clean(node.textContent || node.innerText || '').length;
            if (length >= minLength && length <= maxLength) {
              return node;
            }
            if (length >= minLength) {
              fallback = node;
            }
            node = node.parentElement;
          }
          return fallback || el;
        };
        const ancestorSet = (el) => {
          const nodes = new Set();
          let node = el;
          while (node) {
            nodes.add(node);
            node = node.parentElement;
          }
          return nodes;
        };
        const sharedAncestor = (left, right) => {
          if (!left && !right) return null;
          if (!left) return closestWithText(right, 20);
          if (!right) return closestWithText(left, 20);
          const leftAncestors = ancestorSet(left);
          let node = right;
          while (node) {
            if (leftAncestors.has(node)) {
              return node;
            }
            node = node.parentElement;
          }
          return closestWithText(left, 20);
        };
        const isDoorDashMenuNavLabel = (label, text) => {
          const cleanLabel = clean(label).toLowerCase();
          const lowerText = clean(text).toLowerCase();
          if (/\\$\\d/.test(lowerText)) return false;
          if (/^(all|featured items|most ordered|breads|chicken & wings|chicken wings|oven-baked pastas|oven baked pastas|pastas|desserts|salads|drinks|sandwiches|wings|sides|beverages)$/.test(cleanLabel)) {
            return true;
          }
          if ((/specialty pizzas?|build your own(?: pizza)?/.test(cleanLabel) || /specialty pizzas?|build your own(?: pizza)?/.test(lowerText)) && !/\\$\\d/.test(lowerText)) {
            return true;
          }
          return false;
        };
        const isDoorDashNoise = (text) => /open app|login|log in|become a dasher|merchant|gift cards|notification bell|save$|see all$|pricing & fees|open menu/i.test(text);
        const inferDoorDashGroupKey = (header, text = '') => {
          const combined = clean([header, text].join(' ')).toLowerCase();
          if (!combined) return 'unknown';
          if (/choose your size|\\bsize\\b|\\b10\"\\b|\\b12\"\\b|\\b14\"\\b|\\b16\"\\b/.test(combined)) return 'size';
          if (/topping side|left half|right half|whole/.test(combined)) return 'topping_side';
          if (/\\bcrust\\b|hand tossed|thin crust|brooklyn|gluten free/.test(combined)) return 'crust';
          if (/topping|premium chicken|pineapple|pepperoni|beef|ham|bacon|olive|mushroom|onion|sausage/.test(combined)) return 'topping';
          if (/preferences|special instructions/.test(combined)) return 'preferences';
          return 'unknown';
        };
        const fingerprintForCandidate = ({ role, label, groupKey, groupLabel }) =>
          clean([role, groupKey, groupLabel, label].join(' | ')).toLowerCase();

        const continueAnchor = Array.from(document.querySelectorAll('a[href*="/consumer/checkout"]'))
          .filter(visible)
          .find((el) => /continue|checkout/i.test(labelForElement(el)));
        const cartCloseButton = Array.from(document.querySelectorAll('button[data-testid="dbd-pre-checkout-header-close-button"], button[aria-label="Close"]'))
          .filter(visible)[0] || null;

        const visibleDialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]')).filter(visible);
        const paymentSheet = visibleDialogs.find((el) => /select payment method|credit\\/debit card|paypal|venmo|cash app pay|klarna/i.test(clean(el.innerText)));
        const explicitItemModal = Array.from(document.querySelectorAll('[data-testid="ItemModal"]'))
          .filter(visible)[0];
        const explicitOptionFooter = Array.from(document.querySelectorAll('button[data-testid="optionFooter"]'))
          .filter(visible)[0];
        const itemModal = explicitItemModal
          || explicitOptionFooter?.closest('[data-testid="ItemModal"],[role="dialog"]')
          || visibleDialogs.find((el) => /add to cart|choose your size|recommended options|build your own pizza|custom pizza/i.test(clean(el.innerText)));
        const cartDrawer = continueAnchor || cartCloseButton ? sharedAncestor(continueAnchor, cartCloseButton) : null;
        const cartContinueButton = cartDrawer
          ? Array.from(cartDrawer.querySelectorAll('button,[role="button"],a[href]'))
            .filter(visible)
            .find((el) => {
              const text = clean([labelForElement(el), contextForElement(el, cartDrawer)].join(' '));
              if (!text) return false;
              if (/close|dismiss|address|clear view ct|edit address/i.test(text)) return false;
              return /continue|checkout|review order/i.test(text);
            })
          : null;
        const activeItemModal = cartDrawer ? null : itemModal;
        doordashActiveRoot = paymentSheet || cartDrawer || itemModal || null;
        doordashActiveLayer = paymentSheet ? 'payment_sheet' : cartDrawer ? 'cart_drawer' : itemModal ? 'item_modal' : 'page';
        doordashHasPaymentSheet = Boolean(paymentSheet);
        doordashHasCartCloseCTA = Boolean(cartCloseButton);
        doordashModalTitle = doordashActiveLayer === 'cart_drawer'
          ? 'Cart'
          : clean((doordashActiveRoot?.querySelector('h1,h2,h3,[role="heading"]')?.innerText) || '');

        const storeCardElements = Array.from(document.querySelectorAll('[data-anchor-id="StoreCard"]'))
          .filter(visible)
          .slice(0, 10);
        doordashStoreCardCount = storeCardElements.length;
        storeCardElements.forEach((anchor) => {
          const cardRoot = closestWithText(anchor.parentElement || anchor, 24, 220);
          const headingLabel = Array.from(cardRoot.querySelectorAll('h1,h2,h3,h4,[role="heading"]'))
            .map((node) => clean(node.innerText || ''))
            .find((line) => line && !/^(get to know us|let us help you|doing business|welcome back!?|convenience & drugstores|deals & benefits|featured items|most ordered)$/i.test(line));
          const label = headingLabel || firstMeaningfulTextLine(cardRoot) || labelForElement(anchor);
          pushUnique(doordashCandidates, candidateFromElement(anchor, 'dd_store_card', cardRoot, label));
        });

        const cartReviewButtons = activeItemModal
          ? []
          : Array.from(document.querySelectorAll('button,a[href],[role="button"]'))
            .filter(visible)
            .filter((el) => /view cart|items? in cart|open order cart/i.test(labelForElement(el)));
        cartReviewButtons.slice(0, 4).forEach((button) => {
          doordashHasCartCTA = true;
          const root = closestWithText(button, 12, 180);
          const label = /view cart/i.test(labelForElement(button)) ? 'View cart' : 'Open cart';
          pushUnique(doordashCandidates, candidateFromElement(button, 'dd_cart_cta', root, label));
        });

        const cartButton = activeItemModal
          ? null
          : Array.from(document.querySelectorAll('button[data-testid="OrderCartIconButton"], button[aria-controls="order-cart"]'))
            .filter(visible)[0];
        if (cartButton) {
          doordashHasCartCTA = true;
          pushUnique(doordashCandidates, candidateFromElement(cartButton, 'dd_cart_cta', cartButton.closest('section,div'), 'Open cart'));
        }

        if ((continueAnchor || cartContinueButton) && !activeItemModal) {
          doordashHasContinueCTA = true;
          const continueControl = cartContinueButton || continueAnchor;
          pushUnique(doordashCandidates, candidateFromElement(continueControl, 'dd_continue_cta', cartDrawer || continueControl.closest('section,div'), 'Continue'));
        }

        if (cartCloseButton && cartDrawer) {
          pushUnique(doordashCandidates, candidateFromElement(cartCloseButton, 'dd_modal_close', cartDrawer, 'Close cart'));
        }

        if (activeItemModal) {
          const modalClose = Array.from(activeItemModal.querySelectorAll('button,[role="button"]'))
            .filter(visible)
            .find((el) => /^x$/i.test(labelForElement(el)) || /close|dismiss/i.test(labelForElement(el)));
          if (modalClose) {
            pushUnique(doordashCandidates, candidateFromElement(modalClose, 'dd_modal_close', activeItemModal, 'Close item'));
          }

          const footerActionButtons = Array.from(document.querySelectorAll(
            '#prism-modal-footer button[data-testid="optionFooter"], [data-testid="in-content-modal-footer-container"] button[data-testid="optionFooter"], button[data-testid="optionFooter"]'
          )).filter(visible);
          const addToCartButtons = footerActionButtons
            .filter((el) => /add to cart|update item/i.test(labelForElement(el)))
            .concat(
              Array.from((explicitItemModal || activeItemModal || document).querySelectorAll('button,[role="button"],a[href]'))
                .filter(visible)
                .filter((el) => /add to cart|update item/i.test(labelForElement(el)))
            );
          doordashCustomizerAddToCartLabel = addToCartButtons.length > 0 ? clean(labelForElement(addToCartButtons[0])) : '';
          addToCartButtons.forEach((button) => {
            doordashHasAddToCartCTA = true;
            const root = sharedAncestor(activeItemModal, button) || closestWithText(button, 18, 240);
            pushUnique(doordashCandidates, candidateFromElement(button, 'dd_add_to_cart', root, 'Add to cart', {
              groupKey: 'review',
              groupLabel: 'Add to cart',
              tapFingerprint: fingerprintForCandidate({
                role: 'dd_add_to_cart',
                label: 'Add to cart',
                groupKey: 'review',
                groupLabel: 'Add to cart'
              })
            }));
          });

          const checkedRadios = Array.from(activeItemModal.querySelectorAll('input[type="radio"]:checked')).filter(visible);
          const checkedCheckboxes = Array.from(activeItemModal.querySelectorAll('input[type="checkbox"]:checked')).filter(visible);
          const allOptions = Array.from(activeItemModal.querySelectorAll('input[type="radio"],input[type="checkbox"]')).filter(visible);
          doordashCustomizerCheckedRadioCount = checkedRadios.length;
          doordashCustomizerCheckedCheckboxCount = checkedCheckboxes.length;
          doordashCustomizerOptionCount = allOptions.length;

          const recommendedPresetButtons = Array.from(activeItemModal.querySelectorAll('button,[role="button"]'))
            .filter(visible)
            .filter((el) => /^#\\d+/.test(clean(labelForElement(el))));
          doordashCustomizerRecommendedPresetCount = recommendedPresetButtons.length;

          doordashCustomizerHasSpecialInstructions = Array.from(activeItemModal.querySelectorAll('button,[role="button"],a[href]'))
            .filter(visible)
            .some((el) => /add special instructions/i.test(labelForElement(el)));

          const saveFooterButtons = footerActionButtons;
          saveFooterButtons.forEach((button) => {
            const root = sharedAncestor(activeItemModal, button) || closestWithText(button, 8, 220);
            const label = clean(labelForElement(button));
            if (!label || /add to cart|update item/i.test(label)) {
              return;
            }
            pushUnique(doordashCandidates, candidateFromElement(button, 'dd_modifier_save', root, label, {
              groupKey: 'save',
              groupLabel: 'Save',
              tapFingerprint: fingerprintForCandidate({
                role: 'dd_modifier_save',
                label,
                groupKey: 'save',
                groupLabel: 'Save'
              })
            }));
          });

          const optionRootForElement = (el) => {
            if (!el) return null;
            const id = clean((el.getAttribute && el.getAttribute('id')) || '');
            if (id) {
              try {
                const boundLabel = activeItemModal.querySelector(`label[for="${CSS.escape(id)}"]`);
                if (boundLabel && visible(boundLabel)) {
                  return boundLabel;
                }
              } catch (_) {}
            }
            return el.closest('label,[role="radio"],[role="checkbox"]') || closestWithText(el, 6, 180);
          };

          const customizerGroups = new Map();
          const customizerGroupStats = new Map();
          const optionGroupCache = new WeakMap();
          const groupMapKeyFor = (group) => [clean(group?.header || '').toLowerCase(), group?.groupKey || 'unknown'].join('|');
          const checkedStateForOption = (el, root) => {
            const nodes = [el, root].filter(Boolean);
            for (const node of nodes) {
              const ariaChecked = clean((node.getAttribute && node.getAttribute('aria-checked')) || '').toLowerCase();
              if (ariaChecked === 'true') {
                return true;
              }
              if (node.matches && node.matches('input[type="radio"],input[type="checkbox"]') && node.checked) {
                return true;
              }
              const checkedDescendant = node.querySelector
                ? node.querySelector('input[type="radio"]:checked,input[type="checkbox"]:checked,[role="radio"][aria-checked="true"],[role="checkbox"][aria-checked="true"]')
                : null;
              if (checkedDescendant) {
                return true;
              }
            }
            return false;
          };
          const groupDescriptorForNode = (node) => {
            if (!node || !visible(node)) return null;
            const text = clean(node.textContent || '');
            if (!text || text.length < 12 || text.length > 900) return null;
            if (/^your recommended options\\b/i.test(text)) return null;
            if (!/(required|optional).*(select|choose)|preferences\\s*\\(optional\\)|choose your|topping side|crust|toppings?/i.test(text)) return null;
            const headerNode = node.querySelector('h1,h2,h3,h4,[role="heading"]');
            const heading = clean(headerNode?.textContent || '');
            const firstLine = clean((text.split('\\n').find(Boolean)) || '');
            const hasStructuredMarker = /(required|optional).*(select|choose)|preferences\\s*\\(optional\\)|choose your|add toppings|crust seasoning|topping side/i.test(text);
            const optionDescendants = Array.from(
              node.querySelectorAll('label,input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]')
            ).filter(visible);
            if (!heading && !hasStructuredMarker && optionDescendants.length < 2) return null;
            if (!heading && !hasStructuredMarker && optionDescendants.length <= 1 && /edit selection/i.test(text)) return null;
            const source = heading || text;
            const headerMatch = source.match(/^(.{1,120}?)(?:\\s+(?:Required|\\(Optional\\)|Optional)\\b)/i);
            const header = clean(
              headerMatch
                ? headerMatch[1]
                : (/^preferences\\b/i.test(source) ? 'Preferences' : heading || firstLine)
            );
            if (!header || /^required$/i.test(header) || /^optional$/i.test(header)) return null;
            return {
              header,
              groupKey: inferDoorDashGroupKey(header, text),
              required: /\\brequired\\b/i.test(text),
              text,
              root: node
            };
          };

          const groupForOptionRoot = (root) => {
            if (!root) return null;
            if (optionGroupCache.has(root)) {
              return optionGroupCache.get(root);
            }
            let node = root;
            let group = null;
            for (let depth = 0; node && node !== itemModal && depth < 8; depth += 1, node = node.parentElement) {
              group = groupDescriptorForNode(node);
              if (group) {
                break;
              }
            }
            optionGroupCache.set(root, group);
            if (group) {
              const groupMapKey = groupMapKeyFor(group);
              if (!customizerGroups.has(groupMapKey)) {
                customizerGroups.set(groupMapKey, group);
              }
            }
            return group;
          };
          const opensSubflowForOptionRoot = (root) => {
            if (!root || !root.querySelectorAll) return false;
            return Array.from(root.querySelectorAll('svg path')).some((path) => {
              const d = clean(path.getAttribute('d') || '');
              return d.includes('11.707 7.29289') || d.includes('9.58586 7.99992');
            });
          };

          const seenOptionRoots = new WeakSet();
          const modalOptionButtons = Array.from(activeItemModal.querySelectorAll('label,input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]'))
            .filter(visible)
            .filter((el) => {
              const elementLabel = clean(labelForElement(el));
              if (/^back$/i.test(elementLabel)) {
                return false;
              }
              const root = optionRootForElement(el);
              if (!root || !visible(root)) {
                return false;
              }
              if (seenOptionRoots.has(root)) {
                return false;
              }
              seenOptionRoots.add(root);
              const label = firstMeaningfulTextLine(root) || labelForElement(root) || labelForElement(el);
              const group = groupForOptionRoot(root);
              const text = clean([label, contextForElement(el, root)].join(' '));
              if (!text || isDoorDashNoise(text) || /close|dismiss|add special instructions|add to cart/i.test(text)) {
                return false;
              }
              if (/^your recommended options\\b/i.test(text)) {
                return false;
              }
              if (/recommended|featured|favorites|cookie brownie|lava crunch|parmesan bites|stuffed cheesy bread/i.test(text)) {
                return false;
              }
              if (group && clean(label).toLowerCase() === clean(group.header).toLowerCase()) {
                return false;
              }
              if (/required|optional|choose|select|preferences$/i.test(label)) {
                return false;
              }
              return text.length <= 260;
            })
            .slice(0, 48);
          modalOptionButtons.forEach((el) => {
            const root = optionRootForElement(el) || closestWithText(el, 6, 180);
            const label = firstMeaningfulTextLine(root) || labelForElement(root) || labelForElement(el);
            if (!label) return;
            const group = groupForOptionRoot(root);
            const groupKey = group?.groupKey || inferDoorDashGroupKey(group?.header || '', clean([label, contextForElement(el, root)].join(' ')));
            const groupLabel = group?.header || '';
            const selected = checkedStateForOption(el, root);
            const opensSubflow = opensSubflowForOptionRoot(root);
            const groupMapKey = group ? groupMapKeyFor(group) : '';
            if (group) {
              const stats = customizerGroupStats.get(groupMapKey) || {
                groupKey,
                groupLabel,
                required: Boolean(group?.required),
                optionCount: 0,
                checkedCount: 0,
                order: customizerGroupStats.size
              };
              stats.optionCount += 1;
              if (checkedStateForOption(el, root)) {
                stats.checkedCount += 1;
              }
              customizerGroupStats.set(groupMapKey, stats);
            }
            if (!doordashCustomizerActiveGroupKey) {
              doordashCustomizerActiveGroupKey = groupKey;
              doordashCustomizerActiveGroupLabel = groupLabel;
              doordashCustomizerActiveGroupRequired = Boolean(group?.required);
            }
            doordashItemCardCount += 1;
            pushUnique(
              doordashCandidates,
              candidateFromElement(el, 'dd_modifier_option', root, label, {
                groupKey,
                groupLabel,
                groupRequired: Boolean(group?.required),
                selected,
                opensSubflow,
                tapFingerprint: fingerprintForCandidate({
                  role: 'dd_modifier_option',
                  label,
                  groupKey,
                  groupLabel
                })
              })
            );
          });
          const orderedCustomizerGroups = Array.from(customizerGroupStats.values()).sort((left, right) => left.order - right.order);
          const preferredActiveGroup = orderedCustomizerGroups.find((group) => group.required && group.optionCount > 0 && group.checkedCount === 0)
            || orderedCustomizerGroups.find((group) => group.groupKey !== 'unknown' && group.optionCount > 0 && group.checkedCount === 0)
            || orderedCustomizerGroups.find((group) => group.required && group.optionCount > 0)
            || orderedCustomizerGroups.find((group) => group.groupKey !== 'unknown' && group.optionCount > 0)
            || orderedCustomizerGroups[0];
          if (preferredActiveGroup) {
            doordashCustomizerActiveGroupKey = preferredActiveGroup.groupKey;
            doordashCustomizerActiveGroupLabel = preferredActiveGroup.groupLabel;
            doordashCustomizerActiveGroupRequired = Boolean(preferredActiveGroup.required);
          }
          doordashCustomizerGroupCount = customizerGroups.size;
          doordashCustomizerRequiredGroupCount = Array.from(customizerGroups.values()).filter((group) => group.required).length;
        } else if (!cartDrawer) {
          const explicitMenuCards = Array.from(document.querySelectorAll('[data-testid="MenuItem"][data-item-id]'))
            .filter(visible)
            .slice(0, 28);
          explicitMenuCards.forEach((el) => {
            doordashItemCardCount += 1;
            const titleNode = el.querySelector('[data-telemetry-id="storeMenuItem.title"]') || el.querySelector('h3,[role="heading"]');
            const priceNode = el.querySelector('[data-anchor-id="StoreMenuItemPrice"]');
            const itemLabel = clean(titleNode?.innerText || titleNode?.textContent || firstMeaningfulTextLine(el) || labelForElement(el));
            const priceLabel = clean(priceNode?.innerText || priceNode?.textContent || "");
            const displayLabel = priceLabel.isEmpty ? itemLabel : clean([itemLabel, priceLabel].join(' '));
            pushUnique(doordashCandidates, candidateFromElement(el, 'dd_item_card', el, displayLabel));
          });

          const quickAddButtons = Array.from(document.querySelectorAll('button[data-testid="quick-add-button"]'))
            .filter(visible)
            .slice(0, 8);
          quickAddButtons.forEach((button) => {
            doordashHasAddToCartCTA = true;
            pushUnique(doordashCandidates, candidateFromElement(button, 'dd_add_to_cart', closestWithText(button, 18), 'Add to cart'));
          });

          const explicitStoreItemCards = Array.from(document.querySelectorAll('[role="button"][aria-label], button[aria-label]'))
            .filter(visible)
            .filter((el) => {
              const label = labelForElement(el);
              const root = closestWithText(el, 18, 240);
              const text = clean([label, contextForElement(el, root)].join(' '));
              if (!label || isDoorDashNoise(text)) {
                return false;
              }
              if (/open menu|notification bell|group order|delivery|pickup|save|see more|search stores/i.test(text)) {
                return false;
              }
              return /build your own|specialty pizza|custom pizza|pizza|wings|bread|pasta|dessert|sandwich|salad|bites/i.test(label)
                && (/\\$\\d/.test(text) || label.length >= 6);
            })
            .slice(0, 18);
          explicitStoreItemCards.forEach((el) => {
            doordashItemCardCount += 1;
            const root = closestWithText(el, 18, 240);
            const itemLabel = firstMeaningfulTextLine(root) || clean(labelForElement(el));
            pushUnique(doordashCandidates, candidateFromElement(el, 'dd_item_card', root, itemLabel));
          });

          const storefrontElements = Array.from(document.querySelectorAll('button,a[href],[role="button"]'))
            .filter(visible)
            .slice(0, 140);
          storefrontElements.forEach((el) => {
            const label = labelForElement(el);
            const root = closestWithText(el, 18);
            const context = contextForElement(el, root);
            const text = clean([label, context].join(' '));
            if (!text || isDoorDashNoise(text)) return;
            if ((el.getAttribute('aria-controls') || '') === 'order-cart' || (el.getAttribute('data-testid') || '') === 'OrderCartIconButton') {
              return;
            }
            if (/continue/i.test(text) && !/continue browsing/i.test(text)) {
              doordashHasContinueCTA = true;
              pushUnique(doordashCandidates, candidateFromElement(el, 'dd_continue_cta', root, 'Continue'));
              return;
            }
            if (/add to cart/i.test(text)) {
              doordashHasAddToCartCTA = true;
              pushUnique(doordashCandidates, candidateFromElement(el, 'dd_add_to_cart', root, 'Add to cart'));
              return;
            }
            if (isDoorDashMenuNavLabel(label, text)) {
              pushUnique(doordashCandidates, candidateFromElement(el, 'dd_menu_nav', root, clean(label)));
              return;
            }
            if (/build your own|specialty pizza|custom pizza|pizza|wings|bread|pasta|dessert|sandwich|salad|bites/i.test(text) && (/\\$\\d/.test(text) || (el.getAttribute('role') || '') === 'button' || (el.getAttribute('aria-label') || ''))) {
              doordashItemCardCount += 1;
              const itemLabel = firstMeaningfulTextLine(root) || clean(label);
              pushUnique(doordashCandidates, candidateFromElement(el, 'dd_item_card', root, itemLabel));
            }
          });
        }

        const tipButtons = Array.from(document.querySelectorAll('button[data-anchor-id="TipPickerOption"]'))
          .filter(visible)
          .slice(0, 6);
        doordashTipOptionCount = tipButtons.length;
        tipButtons.forEach((button) => {
          pushUnique(doordashCandidates, candidateFromElement(button, 'dd_tip_option', button.closest('[role="radiogroup"],section,div'), labelForElement(button)));
        });

        const addressButtons = Array.from(document.querySelectorAll('button,[role="button"],a[href]'))
          .filter(visible)
          .filter((el) => /\\d{3,} .*\\b(st|street|rd|road|ct|court|ave|avenue|blvd|lane|ln|drive|dr)\\b/i.test(clean(el.innerText || '')))
          .slice(0, 2);
        doordashHasAddressCTA = addressButtons.length > 0;
        addressButtons.forEach((button) => {
          pushUnique(doordashCandidates, candidateFromElement(button, 'dd_address_cta', button.closest('section,div'), labelForElement(button)));
        });

        if (paymentSheet) {
          Array.from(paymentSheet.querySelectorAll('button,[role="button"]'))
            .filter(visible)
            .forEach((button) => {
              pushUnique(doordashCandidates, candidateFromElement(button, 'dd_payment_method', paymentSheet, labelForElement(button)));
            });
        }
      }

      if (/ubereats\\.com$/i.test(location.hostname)) {
        const pushUnique = (collection, candidate) => {
          if (!candidate || (!candidate.label && !candidate.url)) return;
          const key = [candidate.service_role || '', candidate.label || '', candidate.url || '', candidate.id || ''].join('|');
          if (collection.some((existing) => [existing.service_role || '', existing.label || '', existing.url || '', existing.id || ''].join('|') === key)) {
            return;
          }
          collection.push(candidate);
        };
        const rawLines = (el) => String(el?.innerText || '')
          .split('\\n')
          .map(clean)
          .filter(Boolean);
        const firstMeaningfulTextLine = (el) => {
          const lines = rawLines(el);
          return lines.find((line) => {
            const lower = line.toLowerCase();
            return /[a-z]/i.test(line)
              && !/^(offers|featured items|all stores|all|delivery|pickup|build your cart|order delivery near you)$/i.test(lower)
              && !/delivered by|delivery fee|minutes|mins| mi\\b|\\bmin\\b|reviews?|\\(\\d\\+\\)|results$/i.test(lower);
          }) || lines[0] || '';
        };
        const closestWithText = (el, minLength = 20, maxLength = 260) => {
          let node = el;
          let fallback = el;
          while (node && node !== document.body) {
            const length = clean(node.innerText || '').length;
            if (length >= minLength && length <= maxLength) {
              return node;
            }
            if (length >= minLength) {
              fallback = node;
            }
            node = node.parentElement;
          }
          return fallback || el;
        };
        const ancestorSet = (el) => {
          const nodes = new Set();
          let node = el;
          while (node) {
            nodes.add(node);
            node = node.parentElement;
          }
          return nodes;
        };
        const sharedAncestor = (left, right) => {
          if (!left && !right) return null;
          if (!left) return closestWithText(right, 20);
          if (!right) return closestWithText(left, 20);
          const leftAncestors = ancestorSet(left);
          let node = right;
          while (node) {
            if (leftAncestors.has(node)) {
              return node;
            }
            node = node.parentElement;
          }
          return closestWithText(left, 20);
        };
        const isUberNoise = (text) => /sign up|login redirect|main navigation menu|group order|favorite|view more options|save on ubereats|uber one|offers$|delivery fee$|sort$|rating$|price$|benefits eligible|snap$/i.test(text);
        const uberActionables = Array.from(document.querySelectorAll('a[href],button,[role="button"],[role="option"],input[type="button"],input[type="submit"]'))
          .filter(visible);
        const continueBrowserControl = uberActionables.find((el) => /continue in browser/i.test(clean([labelForElement(el), contextForElement(el)].join(' '))));
        const addressGateControl = uberActionables.find((el) => /enter delivery address/i.test(clean([labelForElement(el), contextForElement(el)].join(' '))));
        const searchEntryControl = Array.from(document.querySelectorAll('[data-testid="header-mobile-search-entry"]'))
          .filter(visible)[0] || uberActionables.find((el) => /search uber eats/i.test(clean([labelForElement(el), contextForElement(el)].join(' '))));
        const addressResults = Array.from(document.querySelectorAll('[data-testid="location-result"], [role="option"][data-testid="location-result"]'))
          .filter(visible)
          .slice(0, 5);
        const addToCartButton = Array.from(document.querySelectorAll('button[data-testid="add-to-cart-button"]'))
          .filter(visible)[0] || uberActionables.find((el) => /add \\d+ to order|add to order/i.test(labelForElement(el)));
        const viewCartButton = Array.from(document.querySelectorAll('a[data-testid="view-cart-button"],button[data-testid="view-cart-button"]'))
          .filter(visible)[0] || uberActionables.find((el) => /view cart|view order/i.test(labelForElement(el)));
        const nextButton = Array.from(document.querySelectorAll('a[data-testid="go-to-checkout-button"],button[data-testid="go-to-checkout-button"]'))
          .filter(visible)[0] || uberActionables.find((el) => /^next$/i.test(labelForElement(el)));
        const modalClose = uberActionables.find((el) => /close/i.test(labelForElement(el)) || /^x$/i.test(labelForElement(el)));
        const itemModal = addToCartButton ? (sharedAncestor(addToCartButton, modalClose) || closestWithText(addToCartButton, 18, 420)) : null;

        ubereatsActiveLayer = addToCartButton ? 'item_modal' : (nextButton || viewCartButton ? 'cart_page' : ((continueBrowserControl || addressGateControl || addressResults.length || searchEntryControl) ? 'entry_gate' : 'page'));
        ubereatsModalTitle = itemModal ? clean((itemModal.querySelector('h1,h2,h3,[role="heading"]')?.innerText) || '') : '';
        ubereatsHasContinueBrowser = Boolean(continueBrowserControl);
        ubereatsHasAddressGate = Boolean(addressGateControl) || addressResults.length > 0;
        ubereatsHasSearchEntry = Boolean(searchEntryControl);

        if (continueBrowserControl) {
          pushUnique(ubereatsCandidates, candidateFromElement(continueBrowserControl, 'ue_continue_browser', closestWithText(continueBrowserControl, 18, 240), 'Continue in browser'));
        }
        if (addressGateControl) {
          pushUnique(ubereatsCandidates, candidateFromElement(addressGateControl, 'ue_address_cta', closestWithText(addressGateControl, 18, 240), 'Enter delivery address'));
        }
        addressResults.forEach((option) => {
          const root = closestWithText(option, 18, 240);
          const label = firstMeaningfulTextLine(root) || labelForElement(option);
          pushUnique(ubereatsCandidates, candidateFromElement(option, 'ue_address_result', root, label));
        });
        if (searchEntryControl) {
          pushUnique(ubereatsCandidates, candidateFromElement(searchEntryControl, 'ue_search_entry', closestWithText(searchEntryControl, 18, 220), 'Search Uber Eats'));
        }

        const storeCards = Array.from(document.querySelectorAll('a[data-testid="store-card"]'))
          .filter(visible)
          .slice(0, 12);
        ubereatsStoreCardCount = storeCards.length;
        storeCards.forEach((anchor) => {
          const root = closestWithText(anchor, 18, 260);
          const headingLabel = Array.from(root.querySelectorAll('h1,h2,h3,h4,[role="heading"]'))
            .map((node) => clean(node.innerText || ''))
            .find((line) => line && !/\\d+ results/i.test(line));
          const label = headingLabel || firstMeaningfulTextLine(root) || labelForElement(anchor);
          pushUnique(ubereatsCandidates, candidateFromElement(anchor, 'ue_store_card', root, label));
        });

        if (addToCartButton) {
          ubereatsHasAddToCartCTA = true;
          pushUnique(ubereatsCandidates, candidateFromElement(addToCartButton, 'ue_add_to_cart', itemModal || closestWithText(addToCartButton, 18, 320), 'Add to order'));
          if (modalClose && itemModal) {
            pushUnique(ubereatsCandidates, candidateFromElement(modalClose, 'ue_modal_close', itemModal, 'Close item'));
          }
        } else {
          const quickAddButtons = Array.from(document.querySelectorAll('button[data-testid="quick-add-button"]'))
            .filter(visible)
            .slice(0, 6);
          quickAddButtons.forEach((button) => {
            ubereatsHasAddToCartCTA = true;
            pushUnique(ubereatsCandidates, candidateFromElement(button, 'ue_add_to_cart', closestWithText(button, 18, 220), 'Quick add'));
          });

          const itemAnchors = Array.from(document.querySelectorAll('a[data-testid^="store-item-"]'))
            .filter(visible)
            .filter((anchor) => {
              const text = clean([labelForElement(anchor), contextForElement(anchor, closestWithText(anchor, 18, 260))].join(' '));
              return text && !isUberNoise(text);
            })
            .slice(0, 18);
          itemAnchors.forEach((anchor) => {
            ubereatsItemCardCount += 1;
            const root = closestWithText(anchor, 18, 260);
            const label = firstMeaningfulTextLine(root) || labelForElement(anchor);
            pushUnique(ubereatsCandidates, candidateFromElement(anchor, 'ue_item_card', root, label));
          });
        }

        if (viewCartButton) {
          ubereatsHasCartCTA = true;
          pushUnique(ubereatsCandidates, candidateFromElement(viewCartButton, 'ue_cart_cta', closestWithText(viewCartButton, 18, 260), 'View order'));
        }
        if (nextButton) {
          ubereatsHasContinueCTA = true;
          pushUnique(ubereatsCandidates, candidateFromElement(nextButton, 'ue_continue_cta', closestWithText(nextButton, 18, 260), 'Next'));
        }
      }

      if (/(^|\\.)uber\\.com$/i.test(location.hostname) && !/ubereats\\.com$/i.test(location.hostname)) {
        const pushUnique = (collection, candidate) => {
          if (!candidate || (!candidate.label && !candidate.url)) return;
          const key = [candidate.service_role || '', candidate.label || '', candidate.url || '', candidate.id || ''].join('|');
          if (collection.some((existing) => [existing.service_role || '', existing.label || '', existing.url || '', existing.id || ''].join('|') === key)) {
            return;
          }
          collection.push(candidate);
        };
        const rawLines = (el) => String(el?.innerText || '')
          .split('\\n')
          .map(clean)
          .filter(Boolean);
        const firstMeaningfulTextLine = (el) => {
          const lines = rawLines(el);
          return lines.find((line) => {
            const lower = line.toLowerCase();
            return /[a-z]/i.test(line)
              && !/^(see prices|book your first ride|get ready for your first trip|plan your journey|ways to ride and more|pickup now|for me|back)$/i.test(lower)
              && !/minutes|mins|eta|arrives|affordable rides|available|up to \\d/i.test(lower);
          }) || lines[0] || '';
        };
        const closestWithText = (el, minLength = 18, maxLength = 320) => {
          let node = el;
          let fallback = el;
          while (node && node !== document.body) {
            const length = clean(node.innerText || '').length;
            if (length >= minLength && length <= maxLength) {
              return node;
            }
            if (length >= minLength) {
              fallback = node;
            }
            node = node.parentElement;
          }
          return fallback || el;
        };
        const isUberRideNoise = (text) => /explore the uber platform|book your first ride|help center|investors|newsroom|blog|learn more|restaurants|hotels|entertainment|transport|attractions|ways to ride and more|plan your journey/i.test(text);
        const rideActionables = Array.from(document.querySelectorAll('a[href],button,[role="button"],[role="option"],input,textarea,select'))
          .filter(visible);
        const pickupInput = Array.from(document.querySelectorAll('input[data-testid="dotcom-ui.pickup-destination.input.pickup"]'))
          .filter(visible)[0] || null;
        const dropoffInput = Array.from(document.querySelectorAll('input[data-testid="dotcom-ui.pickup-destination.input.destination.drop0"]'))
          .filter(visible)[0] || null;
        const pickupLocationButton = Array.from(document.querySelectorAll('[data-testid="clear-button"] [role="button"], [data-testid="clear-button"]'))
          .filter(visible)[0] || null;
        const activeField = pickupInput === document.activeElement
          ? 'pickup'
          : (dropoffInput === document.activeElement || dropoffInput?.getAttribute('aria-expanded') === 'true')
            ? 'dropoff'
            : pickupInput?.getAttribute('aria-expanded') === 'true'
              ? 'pickup'
              : '';
        uberHasPickupInput = Boolean(pickupInput);
        uberHasDropoffInput = Boolean(dropoffInput);
        uberPickupValue = clean(pickupInput?.value || '');
        uberDropoffValue = clean(dropoffInput?.value || '');
        uberPickupMissing = Boolean(pickupInput) && !uberPickupValue;
        uberDropoffMissing = Boolean(dropoffInput) && !uberDropoffValue;
        uberActiveLayer = 'trip_builder';

        if (pickupInput) {
          pushUnique(uberCandidates, candidateFromElement(pickupInput, 'ub_pickup_input', closestWithText(pickupInput, 8, 180), 'Set pickup'));
        }
        if (pickupLocationButton && uberPickupMissing) {
          pushUnique(uberCandidates, candidateFromElement(pickupLocationButton, 'ub_pickup_current_location', closestWithText(pickupLocationButton, 8, 180), 'Use current location'));
        }
        if (dropoffInput) {
          pushUnique(uberCandidates, candidateFromElement(dropoffInput, 'ub_dropoff_input', closestWithText(dropoffInput, 8, 180), 'Set destination'));
        }

        const locationResults = Array.from(document.querySelectorAll('[data-testid="pudo-result"], [role="option"][data-testid="pudo-result"]'))
          .filter(visible)
          .slice(0, 6);
        locationResults.forEach((option) => {
          const root = closestWithText(option, 18, 240);
          const text = clean([labelForElement(option), contextForElement(option, root)].join(' '));
          const role = activeField === 'pickup' || /allow location access|current location|pickup address/i.test(text)
            ? 'ub_pickup_result'
            : 'ub_dropoff_result';
          const label = firstMeaningfulTextLine(root) || labelForElement(option);
          if (role === 'ub_pickup_result') {
            uberPickupResultCount += 1;
          } else {
            uberDropoffResultCount += 1;
          }
          pushUnique(uberCandidates, candidateFromElement(option, role, root, label));
        });

        const seePricesControl = rideActionables.find((el) => /see prices/i.test(clean([labelForElement(el), contextForElement(el)].join(' '))));
        if (seePricesControl) {
          uberHasSeePricesCTA = true;
          pushUnique(uberCandidates, candidateFromElement(seePricesControl, 'ub_see_prices_cta', closestWithText(seePricesControl, 18, 220), 'See prices'));
        }

        const vehicleNodes = Array.from(document.querySelectorAll('button,[role="button"],a[href]'))
          .filter(visible)
          .filter((el) => {
            const text = clean([labelForElement(el), contextForElement(el, closestWithText(el, 18, 320))].join(' '));
            return text
              && !isUberRideNoise(text)
              && /uberx|uberxl|electric|comfort|black|share/i.test(text)
              && /\\$\\d/.test(text);
          })
          .slice(0, 6);
        uberVehicleOptionCount = vehicleNodes.length;
        vehicleNodes.forEach((node) => {
          const root = closestWithText(node, 18, 320);
          const label = firstMeaningfulTextLine(root) || labelForElement(node);
          pushUnique(uberCandidates, candidateFromElement(node, 'ub_vehicle_option', root, label));
        });

        const requestRideButton = Array.from(document.querySelectorAll('button[data-testid="request_trip_button"],a[data-testid="request_trip_button"],button,[role="button"]'))
          .filter(visible)
          .find((el) => /request uber|request trip/i.test(clean([labelForElement(el), contextForElement(el)].join(' '))));
        if (requestRideButton) {
          uberHasRequestCTA = true;
          uberActiveLayer = 'product_selection';
          pushUnique(uberCandidates, candidateFromElement(requestRideButton, 'ub_request_cta', closestWithText(requestRideButton, 18, 240), clean(labelForElement(requestRideButton)) || 'Request ride'));
        }
      }

      const textRoot = (doordashActiveLayer === 'item_modal' || doordashActiveLayer === 'cart_drawer' || doordashActiveLayer === 'payment_sheet')
        ? doordashActiveRoot
        : document.body;
      const text = clean(textRoot ? (textRoot.textContent || textRoot.innerText || '') : '');
      return {
        title: document.title || '',
        url: location.href,
        text_snippet: text.slice(0, 1000),
        headings,
        inputs,
        buttons,
        links,
        candidates,
        doordash_candidates: doordashCandidates.slice(0, 40),
        doordash_active_layer: doordashActiveLayer,
        doordash_modal_title: doordashModalTitle,
        doordash_store_card_count: doordashStoreCardCount,
        doordash_item_card_count: doordashItemCardCount,
        doordash_tip_option_count: doordashTipOptionCount,
        doordash_customizer_group_count: doordashCustomizerGroupCount,
        doordash_customizer_required_group_count: doordashCustomizerRequiredGroupCount,
        doordash_customizer_option_count: doordashCustomizerOptionCount,
        doordash_customizer_checked_radio_count: doordashCustomizerCheckedRadioCount,
        doordash_customizer_checked_checkbox_count: doordashCustomizerCheckedCheckboxCount,
        doordash_customizer_recommended_preset_count: doordashCustomizerRecommendedPresetCount,
        doordash_customizer_has_special_instructions: doordashCustomizerHasSpecialInstructions,
        doordash_customizer_add_to_cart_label: doordashCustomizerAddToCartLabel,
        doordash_customizer_active_group_key: doordashCustomizerActiveGroupKey,
        doordash_customizer_active_group_label: doordashCustomizerActiveGroupLabel,
        doordash_customizer_active_group_required: doordashCustomizerActiveGroupRequired,
        doordash_has_cart_cta: doordashHasCartCTA,
        doordash_has_continue_cta: doordashHasContinueCTA,
        doordash_has_add_to_cart_cta: doordashHasAddToCartCTA,
        doordash_has_address_cta: doordashHasAddressCTA,
        doordash_has_payment_sheet: doordashHasPaymentSheet,
        doordash_has_cart_close_cta: doordashHasCartCloseCTA,
        ubereats_candidates: ubereatsCandidates.slice(0, 40),
        ubereats_active_layer: ubereatsActiveLayer,
        ubereats_modal_title: ubereatsModalTitle,
        ubereats_store_card_count: ubereatsStoreCardCount,
        ubereats_item_card_count: ubereatsItemCardCount,
        ubereats_has_cart_cta: ubereatsHasCartCTA,
        ubereats_has_continue_cta: ubereatsHasContinueCTA,
        ubereats_has_add_to_cart_cta: ubereatsHasAddToCartCTA,
        ubereats_has_address_gate: ubereatsHasAddressGate,
        ubereats_has_continue_browser: ubereatsHasContinueBrowser,
        ubereats_has_search_entry: ubereatsHasSearchEntry,
        uber_candidates: uberCandidates.slice(0, 40),
        uber_active_layer: uberActiveLayer,
        uber_pickup_value: uberPickupValue,
        uber_dropoff_value: uberDropoffValue,
        uber_pickup_missing: uberPickupMissing,
        uber_dropoff_missing: uberDropoffMissing,
        uber_pickup_result_count: uberPickupResultCount,
        uber_dropoff_result_count: uberDropoffResultCount,
        uber_vehicle_option_count: uberVehicleOptionCount,
        uber_has_pickup_input: uberHasPickupInput,
        uber_has_dropoff_input: uberHasDropoffInput,
        uber_has_see_prices_cta: uberHasSeePricesCTA,
        uber_has_request_cta: uberHasRequestCTA
      };
      } catch (error) {
        return {
          memla_js_script: 'page_inspection',
          memla_js_error: String(error),
          memla_js_stack: String((error && error.stack) || '')
        };
      }
    })();
    """

    private static let doorDashStorefrontPeekScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const menuCards = Array.from(document.querySelectorAll('[data-testid="MenuItem"][data-item-id]'))
        .filter(visible);
      const menuTail = menuCards[menuCards.length - 1];
      if (menuTail && typeof menuTail.scrollIntoView === 'function') {
        menuTail.scrollIntoView({ block: 'center', inline: 'nearest' });
        return { ok: true, reason: 'scrolled_to_menu_card_tail' };
      }
      const candidates = Array.from(document.querySelectorAll('[role="button"][aria-label], button[aria-label], h2, h3, [role="heading"]'))
        .filter(visible);
      const target = candidates.find((el) => {
        const text = clean(el.getAttribute('aria-label') || el.innerText || '');
        return /build your own|specialty pizza|featured items|most ordered|pizza|wings|breads|dessert|sandwich|salad|pasta/i.test(text);
      });
      if (target && typeof target.scrollIntoView === 'function') {
        target.scrollIntoView({ block: 'center', inline: 'nearest' });
        return { ok: true, reason: 'scrolled_to_menu_target' };
      }
      window.scrollBy(0, Math.min(Math.max(window.innerHeight * 0.9, 320), 720));
      return { ok: true, reason: 'scrolled_storefront_down' };
      } catch (error) {
        return {
          ok: false,
          reason: 'memla_js_exception',
          memla_js_script: 'dd_storefront_peek',
          memla_js_error: String(error),
          memla_js_stack: String((error && error.stack) || '')
        };
      }
    })();
    """

    private static let pageGroundingProbeScript = """
    (() => {
      try {
      const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 1 && rect.height > 1;
      };
      const visibleControls = Array.from(document.querySelectorAll('h1,h2,h3,button,a[href],[role="dialog"],[aria-modal="true"]'))
        .filter(visible)
        .slice(0, 14)
        .map((el) => clean(el.textContent || el.innerText || el.getAttribute('aria-label') || el.getAttribute('title')))
        .filter(Boolean)
        .join(' | ')
        .slice(0, 320);
      const activeModal = Array.from(document.querySelectorAll('[data-testid="ItemModal"],[role="dialog"],[aria-modal="true"]'))
        .filter(visible)[0] || null;
      const textRoot = activeModal || document.body;
      const bodyText = clean(textRoot ? (textRoot.textContent || textRoot.innerText || '') : '').slice(0, 320);
      return {
        fingerprint: [location.href, document.title || '', visibleControls, bodyText].join(' || ')
      };
      } catch (_) {
        return {
          fingerprint: ''
        };
      }
    })();
    """
}

struct MemlaBrowserWebView: UIViewRepresentable {
    @ObservedObject var browser: MemlaBrowserModel

    func makeUIView(context: Context) -> WKWebView {
        browser.webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
    }
}

struct MemlaBrowserView: View {
    let route: MemlaBrowserRoute

    @Environment(\.dismiss) private var dismiss
    @StateObject private var browser = MemlaBrowserModel()
    @State private var verifiedItems: Set<String> = []
    @State private var isCapsuleExpanded = false
    @State private var isC2AConsoleExpanded = false
    @State private var isC2AConsoleClosed = false
    @State private var isRawPageVisible = false
    @State private var authNotes: [String: String] = [:]
    @State private var autoDriveEnabled = false
    @State private var autoDriveStatus = "Manual Mirror mode. Tap the distilled controls yourself."
    @State private var debugCopyStatus = ""
    @State private var debugUploadStatus = ""
    @State private var lastDebugUploadMarker = ""
    @State private var lastAutoDriveSignature = ""
    @State private var pendingDoorDashRole: String = ""
    @State private var pendingDoorDashLabel: String = ""
    @State private var addToCartRetryCount = 0
    @State private var preferCartProgress = false
    @State private var completedModifierTerms: Set<String> = []
    @State private var inFlightModifierTerms: Set<String> = []
    @State private var doorDashModifierCommitPending = false
    @State private var doorDashPendingCommitKind = ""
    @State private var primaryFoodItemAdded = false
    @State private var inProgressPrimaryItemLabel = ""
    @State private var traversedDoorDashDerivedGroups: Set<DoorDashCustomizerGroupKind> = []
    @State private var pendingFoodAddOns: [String] = []
    @State private var pendingFoodAddOperation = ""
    @State private var agencyTrace: [String] = []
    @State private var lastAgencyPageMarker = ""
    @State private var lastDoorDashPlannerMarker = ""
    @State private var lastModifierSelectionLabel = ""
    @State private var lastModifierSelectionGroupKey = ""
    @State private var lastModifierSelectionAt = Date.distantPast
    @State private var pendingStepActionRole = ""
    @State private var pendingStepActionLabel = ""
    @State private var pendingStepTargetGroupKey = ""
    @State private var pendingStepTargetGroupLabel = ""
    @State private var pendingStepTargetTapFingerprint = ""
    @State private var pendingStepTargetOpensSubflow = false
    @State private var pendingStepActionSignature = ""
    @State private var pendingStepActionAt = Date.distantPast
    @State private var pendingStepTapAcknowledged = false
    @State private var pendingStepTapVerifiedSelection = false
    @State private var pendingStepObservedGroupKey = ""
    @State private var pendingStepObservedGroupLabel = ""
    @State private var pendingStepObservedCheckedRadioCount = 0
    @State private var pendingStepObservedCheckedCheckboxCount = 0
    @State private var pendingStepConsumedTerms: Set<String> = []
    @State private var pendingStepCommitKind = ""
    @State private var pendingStepTapRetryCount = 0
    @State private var doorDashReviewBridgePending = false
    @State private var autoDriveEpoch = 0

    private struct MirrorAutoDriveAction {
        let candidate: WebsiteC2ACandidate
        let allowCaution: Bool
        let status: String
        let pendingRole: String
        let consumedTerms: [String]

        init(
            candidate: WebsiteC2ACandidate,
            allowCaution: Bool,
            status: String,
            pendingRole: String,
            consumedTerms: [String] = []
        ) {
            self.candidate = candidate
            self.allowCaution = allowCaution
            self.status = status
            self.pendingRole = pendingRole
            self.consumedTerms = consumedTerms
        }
    }

    private let commerceChecklist = [
        "restaurant_match",
        "item_match",
        "modifier_match",
        "tip_match",
        "delivery_address_match",
        "total_price_limit",
        "user_checkout_confirmation",
    ]

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                capsulePanel
                if let state = browser.websiteState {
                    mirrorPrimarySurface(for: state)
                } else {
                    mirrorLoadingSurface
                }
                rawPageSurface
            }
            .navigationTitle("Memla Browser")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
            .onAppear {
                autoDriveEnabled = false
                autoDriveStatus = "Manual Mirror mode. Tap the distilled controls yourself."
                debugCopyStatus = ""
                debugUploadStatus = ""
                lastDebugUploadMarker = ""
                lastAutoDriveSignature = ""
                pendingDoorDashRole = ""
                pendingDoorDashLabel = ""
                addToCartRetryCount = 0
                preferCartProgress = false
                completedModifierTerms = []
                inFlightModifierTerms = []
                doorDashModifierCommitPending = false
                doorDashPendingCommitKind = ""
                lastModifierSelectionLabel = ""
                lastModifierSelectionGroupKey = ""
                lastModifierSelectionAt = .distantPast
                primaryFoodItemAdded = false
                inProgressPrimaryItemLabel = ""
                traversedDoorDashDerivedGroups = []
                doorDashReviewBridgePending = false
                pendingFoodAddOns = initialFoodAddOns(from: route.capsule)
                pendingFoodAddOperation = ""
                agencyTrace = []
                lastAgencyPageMarker = ""
                lastDoorDashPlannerMarker = ""
                pendingStepActionRole = ""
                pendingStepActionLabel = ""
                pendingStepTargetGroupKey = ""
                pendingStepTargetGroupLabel = ""
                pendingStepTargetTapFingerprint = ""
                pendingStepActionSignature = ""
                pendingStepActionAt = .distantPast
                pendingStepTapAcknowledged = false
                pendingStepTapVerifiedSelection = false
                pendingStepObservedGroupKey = ""
                pendingStepObservedGroupLabel = ""
                pendingStepObservedCheckedRadioCount = 0
                pendingStepObservedCheckedCheckboxCount = 0
                pendingStepConsumedTerms = []
                pendingStepCommitKind = ""
                autoDriveEpoch = 0
                browser.startGrounding(capsule: route.capsule)
                if browser.currentURL.isEmpty {
                    browser.navigate(to: route.url, autoInspect: true, capsule: route.capsule)
                }
            }
            .onDisappear {
                browser.stopGrounding()
            }
            .onReceive(browser.$websiteState.compactMap { $0 }) { state in
                if autoDriveEnabled {
                    let marker = "\(state.pageKind)||\(browser.currentURL)"
                    if marker != lastAgencyPageMarker {
                        lastAgencyPageMarker = marker
                        appendAgencyTrace("Page: \(state.pageKind) • \(state.summary)")
                    }
                }
                handleAutoDriveUpdate(for: state)
            }
            .onReceive(browser.$buttonActionStatus.removeDuplicates()) { status in
                guard autoDriveEnabled, !status.isEmpty else {
                    return
                }
                appendAgencyTrace("Button: \(status)")
                let lowered = status.lowercased()
                let failed = lowered.contains("blocked")
                    || lowered.contains("returned no page result")
                    || lowered.contains("not found")
                    || lowered.contains("policy")
                let succeeded = lowered.contains("tapped ")
                    || lowered.contains("save option")
                    || lowered.contains("already selected")
                    || lowered.contains("field focused")
                if pendingStepActionRole.hasPrefix("dd_modifier") {
                    if failed {
                        if shouldBridgeDoorDashReviewAfterSaveFailure(status: status, state: browser.websiteState) {
                            doorDashReviewBridgePending = true
                            appendAgencyTrace("DoorDash review CTA is now expected. Re-planning for Add to cart.")
                            lastAutoDriveSignature = ""
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                                guard autoDriveEnabled,
                                      !browser.isLoading,
                                      !browser.isInspecting,
                                      !browser.isRunningButtonAction else {
                                    return
                                }
                                browser.inspectPage(capsule: route.capsule)
                            }
                        }
                        sendBrowserDebugSnapshot(reason: "button_status_failed:\(status)", state: browser.websiteState, force: true)
                        rollbackPendingDoorDashStepFailure()
                    } else if succeeded {
                        pendingStepTapAcknowledged = true
                        if pendingStepActionRole == "dd_modifier_option", lowered.contains("verified") {
                            pendingStepTapVerifiedSelection = true
                        }
                        appendAgencyTrace("DoorDash tap acknowledged. Waiting for mirror confirmation.")
                        sendBrowserDebugSnapshot(reason: "button_status_ack:\(status)", state: browser.websiteState, force: true)
                    }
                }
            }
            .onReceive(browser.$searchActionStatus.removeDuplicates()) { status in
                guard autoDriveEnabled, !status.isEmpty else {
                    return
                }
                appendAgencyTrace("Search: \(status)")
            }
            .onReceive(browser.$inspectionStatus.removeDuplicates()) { status in
                guard autoDriveEnabled, !status.isEmpty else {
                    return
                }
                let lowered = status.lowercased()
                if lowered.contains("timed out") || lowered.contains("memla_js_exception") {
                    sendBrowserDebugSnapshot(reason: "inspection_status=\(status)", state: browser.websiteState)
                }
            }
        }
    }

    private var hasC2AConsole: Bool {
        browser.websiteState != nil || !browser.inspectionStatus.isEmpty
    }

    private var mirrorLoadingSurface: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                mirrorSectionCard(title: "Memla's Mirror", systemImage: "sparkles.rectangle.stack") {
                    Text(browser.inspectionStatus.isEmpty ? "Memla is loading the page and preparing a distilled task surface." : browser.inspectionStatus)
                        .font(.subheadline)
                    Text("The raw website stays underneath as execution substrate, but the goal is for you to mostly interact with Memla's simplified view.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        Button(browser.isInspecting ? "Inspecting..." : "Inspect Page") {
                            browser.inspectPage(capsule: route.capsule)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(browser.isInspecting || browser.isLoading)

                        Button(isRawPageVisible ? "Hide Raw Page" : "Show Raw Page") {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isRawPageVisible.toggle()
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                }
            }
            .padding(12)
        }
        .background(Color(.systemGroupedBackground))
    }

    private var rawPageSurface: some View {
        VStack(spacing: 0) {
            Divider()
            ZStack(alignment: .top) {
                VStack(spacing: 0) {
                    if isRawPageVisible {
                        browserToolbar
                        Divider()
                    }
                    ZStack(alignment: .bottom) {
                        MemlaBrowserWebView(browser: browser)
                            .frame(height: isRawPageVisible ? 360 : 360)
                            .frame(height: isRawPageVisible ? 360 : 1, alignment: .top)
                            .opacity(isRawPageVisible ? 1 : 0.02)
                            .allowsHitTesting(isRawPageVisible)
                            .clipped()
                        if isRawPageVisible, hasC2AConsole, !isC2AConsoleClosed {
                            websiteC2AConsole
                        }
                    }
                }
                if !isRawPageVisible {
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Raw Page Hidden")
                                .font(.caption.weight(.semibold))
                            Text("Memla is keeping the website mounted underneath so the mirror can keep reading and steering it.")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        Spacer()
                        Button("Show Raw Page") {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isRawPageVisible = true
                                isC2AConsoleClosed = false
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Color(.secondarySystemBackground))
                }
            }
        }
    }

    private var capsulePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(route.capsule?.title ?? "Web Bridge")
                        .font(.headline)
                    Text(route.option?.label ?? "Memla-controlled web surface")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if browser.isLoading {
                    ProgressView()
                }
                if route.capsule != nil {
                    Button(isCapsuleExpanded ? "Hide" : "Plan") {
                        isCapsuleExpanded.toggle()
                    }
                    .buttonStyle(.bordered)
                    .font(.caption)
                    if autoDriveEnabled {
                        Button("Pause") {
                            toggleAgency()
                        }
                        .buttonStyle(.borderedProminent)
                        .font(.caption)
                    } else {
                        Button("Agency") {
                            toggleAgency()
                        }
                        .buttonStyle(.bordered)
                        .font(.caption)
                    }
                }
            }

            if let capsule = route.capsule {
                if !capsule.slots.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        if let commerceSummary = commerceIntentSummary(for: capsule), !commerceSummary.isEmpty {
                            Text(commerceSummary)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(3)
                        }
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 8, alignment: .leading)], alignment: .leading, spacing: 8) {
                            ForEach(orderedCapsuleSlotEntries(for: capsule), id: \.key) { entry in
                                capsuleChip(title: readableCapsuleSlotTitle(entry.key), value: entry.value)
                            }
                        }
                    }
                }
                if isCapsuleExpanded {
                    Text(capsule.summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                    verificationChecklist(for: capsule)
                } else {
                    Text("Tap Plan for checklist and blockers. Stop before the final purchase/send action.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            } else {
                Text("Memla is keeping this web path inside its own browser surface so future page-state checks can attach here.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .background(Color(.secondarySystemBackground))
    }

    private func orderedCapsuleSlotEntries(for capsule: ActionCapsule) -> [(key: String, value: String)] {
        let preferredOrder = [
            "service",
            "restaurant",
            "item",
            "size",
            "toppings",
            "add_ons",
            "modifiers",
            "tip",
            "destination",
            "pickup_time",
        ]
        let orderIndex = Dictionary(uniqueKeysWithValues: preferredOrder.enumerated().map { ($0.element, $0.offset) })
        return capsule.slots
            .filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .sorted { left, right in
                let leftIndex = orderIndex[left.key] ?? Int.max
                let rightIndex = orderIndex[right.key] ?? Int.max
                if leftIndex != rightIndex {
                    return leftIndex < rightIndex
                }
                return left.key < right.key
            }
            .map { (key: $0.key, value: $0.value) }
    }

    private func readableCapsuleSlotTitle(_ key: String) -> String {
        switch key {
        case "add_ons":
            return "Add Ons"
        case "pickup_time":
            return "Pickup Time"
        default:
            return key.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private func commerceIntentSummary(for capsule: ActionCapsule) -> String? {
        guard let service = capsule.slots["service"], ["DoorDash", "Uber Eats", "food delivery"].contains(service) else {
            return nil
        }
        var parts: [String] = []
        if let item = capsule.slots["item"], !item.isEmpty {
            if let size = capsule.slots["size"], !size.isEmpty {
                parts.append("\(size) \(item)")
            } else {
                parts.append(item)
            }
        }
        if let toppings = capsule.slots["toppings"], !toppings.isEmpty {
            parts.append("Toppings: \(toppings)")
        }
        if let addOns = capsule.slots["add_ons"], !addOns.isEmpty {
            parts.append("Add ons: \(addOns)")
        }
        if let tip = capsule.slots["tip"], !tip.isEmpty {
            parts.append("Tip: \(tip)")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " • ")
    }

    private func toggleAgency() {
        autoDriveEnabled.toggle()
        lastAutoDriveSignature = ""
        addToCartRetryCount = 0
        pendingDoorDashRole = ""
        pendingDoorDashLabel = ""
        pendingFoodAddOperation = ""
        completedModifierTerms = []
        inFlightModifierTerms = []
        doorDashModifierCommitPending = false
        doorDashPendingCommitKind = ""
        lastModifierSelectionLabel = ""
        lastModifierSelectionGroupKey = ""
        lastModifierSelectionAt = .distantPast
        inProgressPrimaryItemLabel = ""
        traversedDoorDashDerivedGroups = []
        doorDashReviewBridgePending = false
        pendingStepActionRole = ""
        pendingStepActionLabel = ""
        pendingStepTargetGroupKey = ""
        pendingStepTargetGroupLabel = ""
        pendingStepTargetTapFingerprint = ""
        pendingStepTargetOpensSubflow = false
        pendingStepActionSignature = ""
        pendingStepActionAt = .distantPast
        pendingStepTapAcknowledged = false
        pendingStepTapVerifiedSelection = false
        pendingStepObservedGroupKey = ""
        pendingStepObservedGroupLabel = ""
        pendingStepObservedCheckedRadioCount = 0
        pendingStepObservedCheckedCheckboxCount = 0
        pendingStepConsumedTerms = []
        pendingStepCommitKind = ""
        autoDriveEpoch += 1
        primaryFoodItemAdded = false
        pendingFoodAddOns = initialFoodAddOns(from: route.capsule)
        preferCartProgress = false
        lastAgencyPageMarker = ""
        lastDoorDashPlannerMarker = ""
        autoDriveStatus = autoDriveEnabled
            ? "Agency is active. Memla will drive to cart review."
            : "Manual Mirror mode. Tap the distilled controls yourself."
        if autoDriveEnabled {
            agencyTrace = []
            appendAgencyTrace("Agency enabled.")
        } else {
            appendAgencyTrace("Agency paused.")
        }
        if autoDriveEnabled, let state = browser.websiteState {
            handleAutoDriveUpdate(for: state)
        }
    }

    private func appendAgencyTrace(_ message: String) {
        let clean = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else {
            return
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        let line = "[\(formatter.string(from: Date()))] \(clean)"
        if agencyTrace.first?.hasSuffix(clean) == true {
            return
        }
        agencyTrace.insert(line, at: 0)
        if agencyTrace.count > 60 {
            agencyTrace = Array(agencyTrace.prefix(60))
        }
    }

    private func doorDashFactInt(_ state: WebsiteC2AState, key: String) -> Int {
        Int(state.serviceFacts[key] ?? "") ?? 0
    }

    private func initialFoodAddOns(from capsule: ActionCapsule?) -> [String] {
        guard let raw = capsule?.slots["add_ons"]?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else {
            return []
        }
        return splitCommerceTerms(raw)
    }

    private func splitCommerceTerms(_ raw: String) -> [String] {
        raw
            .replacingOccurrences(of: " and ", with: ",")
            .components(separatedBy: CharacterSet(charactersIn: ",/+&"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func normalizedCommerceTerm(_ value: String) -> String {
        value
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func orderSpecValues(_ extractor: (OrderSpec) -> OrderSpecField) -> [String] {
        guard let spec = route.capsule?.orderSpec else {
            return []
        }
        return extractor(spec).values
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func currentFoodTargetTerms() -> [String] {
        let unfinishedPrimaryCustomizer = !primaryFoodItemAdded
            && !inProgressPrimaryItemLabel.isEmpty
            && (!completedModifierTerms.isEmpty
                || !inFlightModifierTerms.isEmpty
                || doorDashModifierCommitPending
                || pendingStepActionRole.hasPrefix("dd_modifier"))
        if unfinishedPrimaryCustomizer {
            return expandedCommerceTerms(from: [inProgressPrimaryItemLabel])
        }
        if primaryFoodItemAdded, let addOn = pendingFoodAddOns.first {
            return expandedCommerceTerms(from: splitCommerceTerms(addOn))
        }
        let specItems = orderSpecValues { $0.item }
        if !specItems.isEmpty {
            return expandedCommerceTerms(from: specItems)
        }
        guard let capsule = route.capsule else {
            return []
        }
        return expandedCommerceTerms(from: splitCommerceTerms(capsule.slots["item"] ?? ""))
    }

    private enum FoodModifierStage {
        case size
        case toppings
        case modifiers
        case none
    }

    private func currentModifierTargets() -> (stage: FoodModifierStage, terms: [String]) {
        guard let capsule = route.capsule else {
            return (.none, [])
        }
        if primaryFoodItemAdded {
            return (.none, [])
        }
        let specSizes = orderSpecValues { $0.size }
        if let size = specSizes.first ?? capsule.slots["size"], !size.isEmpty {
            let normalizedSize = normalizedCommerceTerm(size)
            if !normalizedSize.isEmpty
                && !completedModifierTerms.contains(normalizedSize)
                && !inFlightModifierTerms.contains(normalizedSize)
            {
                return (.size, [normalizedSize])
            }
        }
        let specToppings = orderSpecValues { $0.toppings }
        if !specToppings.isEmpty || !(capsule.slots["toppings"] ?? "").isEmpty {
            let remainingToppings = (specToppings.isEmpty ? splitCommerceTerms(capsule.slots["toppings"] ?? "") : specToppings)
                .map(normalizedCommerceTerm)
                .filter { !$0.isEmpty && !completedModifierTerms.contains($0) && !inFlightModifierTerms.contains($0) }
            if let nextTopping = remainingToppings.first {
                return (.toppings, [nextTopping])
            }
        } else if let modifiers = capsule.slots["modifiers"], !modifiers.isEmpty {
            let remainingModifiers = splitCommerceTerms(modifiers)
                .map(normalizedCommerceTerm)
                .filter { !$0.isEmpty && !completedModifierTerms.contains($0) && !inFlightModifierTerms.contains($0) }
            if let nextModifier = remainingModifiers.first {
                return (.modifiers, [nextModifier])
            }
        }
        return (.none, [])
    }

    private func preferredDoorDashGroupKinds(for stage: FoodModifierStage) -> Set<DoorDashCustomizerGroupKind> {
        switch stage {
        case .size:
            return [.size]
        case .toppings:
            return [.topping, .toppingSide]
        case .modifiers:
            return [.preferences, .unknown]
        case .none:
            return [.unknown, .review]
        }
    }

    private func requestedDoorDashSizeTerm() -> String? {
        guard let capsule = route.capsule else {
            return nil
        }
        let specSizes = orderSpecValues { $0.size }
        guard let size = specSizes.first ?? capsule.slots["size"], !size.isEmpty else {
            return nil
        }
        let normalized = normalizedCommerceTerm(size)
        return normalized.isEmpty ? nil : normalized
    }

    private func preservedDoorDashGroupKinds(for stage: FoodModifierStage) -> Set<DoorDashCustomizerGroupKind> {
        var groups = Set<DoorDashCustomizerGroupKind>()
        if requestedDoorDashSizeTerm() != nil, stage != .size {
            groups.insert(.size)
        }
        return groups
    }

    private func unresolvedRequiredDoorDashGroup(
        in candidates: [WebsiteC2ACandidate],
        traversedDerivedGroups: Set<DoorDashCustomizerGroupKind>,
        excluding excludedGroups: Set<DoorDashCustomizerGroupKind>
    ) -> (kind: DoorDashCustomizerGroupKind, label: String)? {
        struct GroupStats {
            var label: String
            var required: Bool
            var hasResolvedSelection: Bool
            var order: Int
        }

        var statsByGroup: [DoorDashCustomizerGroupKind: GroupStats] = [:]
        for (index, candidate) in candidates.enumerated() {
            guard candidate.role == "dd_modifier_option", !candidate.blocked else {
                continue
            }
            let kind = doorDashGroupKind(for: candidate)
            guard kind != .unknown, !excludedGroups.contains(kind) else {
                continue
            }
            let resolvedSelection = candidate.isSelected
                && (!candidate.opensSubflow || traversedDerivedGroups.contains(kind))
            var stats = statsByGroup[kind] ?? GroupStats(
                label: candidate.groupLabel,
                required: candidate.groupRequired,
                hasResolvedSelection: resolvedSelection,
                order: index
            )
            if stats.label.isEmpty {
                stats.label = candidate.groupLabel
            }
            stats.required = stats.required || candidate.groupRequired
            stats.hasResolvedSelection = stats.hasResolvedSelection || resolvedSelection
            statsByGroup[kind] = stats
        }

        return statsByGroup
            .filter { $0.value.required && !$0.value.hasResolvedSelection }
            .sorted { left, right in
                if left.value.order == right.value.order {
                    return left.key.rawValue < right.key.rawValue
                }
                return left.value.order < right.value.order
            }
            .map { (kind: $0.key, label: $0.value.label) }
            .first
    }

    private func selectedDoorDashModifierCandidate(
        in candidates: [WebsiteC2ACandidate],
        group: DoorDashCustomizerGroupKind
    ) -> WebsiteC2ACandidate? {
        guard group != .unknown else {
            return nil
        }
        let selected = candidates.filter {
            $0.role == "dd_modifier_option"
                && !$0.blocked
                && $0.isSelected
                && doorDashGroupKind(for: $0) == group
        }
        return selected.first(where: { $0.opensSubflow }) ?? selected.first
    }

    private func expandedCommerceTerms(from rawTerms: [String]) -> [String] {
        var ordered: [String] = []
        for raw in rawTerms {
            let normalized = normalizedCommerceTerm(raw)
            guard !normalized.isEmpty else { continue }
            ordered.append(normalized)
            let parts = normalized.split(separator: " ").map(String.init)
            if parts.count > 1, let last = parts.last, last.count > 2 {
                ordered.append(last)
            }
        }
        var seen = Set<String>()
        return ordered.filter { seen.insert($0).inserted }
    }

    private func allRequestedModifierTerms() -> [String] {
        guard let capsule = route.capsule else {
            return []
        }
        var requested: [String] = []
        let specSizes = orderSpecValues { $0.size }
        if let size = specSizes.first ?? capsule.slots["size"], !size.isEmpty {
            requested.append(contentsOf: expandedCommerceTerms(from: [size]))
        }
        let specToppings = orderSpecValues { $0.toppings }
        if !specToppings.isEmpty {
            requested.append(contentsOf: expandedCommerceTerms(from: specToppings))
        } else if let toppings = capsule.slots["toppings"], !toppings.isEmpty {
            requested.append(contentsOf: expandedCommerceTerms(from: splitCommerceTerms(toppings)))
        } else if let modifiers = capsule.slots["modifiers"], !modifiers.isEmpty {
            requested.append(contentsOf: expandedCommerceTerms(from: splitCommerceTerms(modifiers)))
        }
        var seen = Set<String>()
        return requested.filter { seen.insert($0).inserted }
    }

    private func doorDashGroupKind(from raw: String) -> DoorDashCustomizerGroupKind {
        DoorDashCustomizerGroupKind(rawValue: raw) ?? .unknown
    }

    private func doorDashGroupKind(for candidate: WebsiteC2ACandidate) -> DoorDashCustomizerGroupKind {
        doorDashGroupKind(from: candidate.groupKey)
    }

    private func doorDashActiveGroupKind(from state: WebsiteC2AState, candidates: [WebsiteC2ACandidate]) -> DoorDashCustomizerGroupKind {
        let explicit = doorDashGroupKind(from: state.serviceFacts["dd_active_group_key"] ?? "")
        if explicit != .unknown {
            return explicit
        }
        let grouped = Dictionary(grouping: candidates.filter { $0.role == "dd_modifier_option" && !$0.groupKey.isEmpty }) { candidate in
            candidate.groupKey
        }
        let best = grouped.max { left, right in
            if left.value.count == right.value.count {
                return left.key < right.key
            }
            return left.value.count < right.value.count
        }?.key ?? ""
        return doorDashGroupKind(from: best)
    }

    private func doorDashActiveGroupLabel(from state: WebsiteC2AState, candidates: [WebsiteC2ACandidate]) -> String {
        if let explicit = state.serviceFacts["dd_active_group_label"], !explicit.isEmpty {
            return explicit
        }
        return candidates.first(where: { $0.role == "dd_modifier_option" && !$0.groupLabel.isEmpty })?.groupLabel ?? ""
    }

    private func candidateMatchedTargetTerms(_ candidate: WebsiteC2ACandidate, targetTerms: [String]) -> [String] {
        let label = normalizedCommerceTerm(candidate.label)
        let matchedTerms = candidate.matchedTerms.map(normalizedCommerceTerm)
        let reason = normalizedCommerceTerm(candidate.reason)
        return targetTerms.filter { term in
            guard !term.isEmpty else { return false }
            if label == term || label.contains(term) || term.contains(label) {
                return true
            }
            if matchedTerms.contains(where: { $0 == term || $0.contains(term) || term.contains($0) }) {
                return true
            }
            let termTokens = term.split(separator: " ")
            if !termTokens.isEmpty, termTokens.allSatisfy({ token in label.contains(token) || reason.contains(token) }) {
                return true
            }
            return false
        }
    }

    private func candidateMatchedModifierTerms(_ candidate: WebsiteC2ACandidate, targetTerms: [String]) -> [String] {
        let label = normalizedCommerceTerm(candidate.label)
        let labelTokens = Set(label.split(separator: " ").map(String.init))
        return targetTerms.filter { term in
            guard !term.isEmpty else { return false }
            if label == term || label.contains(term) || term.contains(label) {
                return true
            }
            let termTokens = term.split(separator: " ").map(String.init)
            guard !termTokens.isEmpty else {
                return false
            }
            return termTokens.allSatisfy { token in
                labelTokens.contains(token) || label.contains(token)
            }
        }
    }

    private func bestCandidate(role: String, in candidates: [WebsiteC2ACandidate], targetTerms: [String]) -> (candidate: WebsiteC2ACandidate, matched: [String])? {
        let relevant = candidates.filter { $0.role == role && !$0.blocked }
        guard !relevant.isEmpty else {
            return nil
        }
        let scored = relevant.compactMap { candidate -> (WebsiteC2ACandidate, [String], Double)? in
            let matched = candidateMatchedTargetTerms(candidate, targetTerms: targetTerms)
            guard !matched.isEmpty else { return nil }
            let label = normalizedCommerceTerm(candidate.label)
            let specificity = matched.reduce(0.0) { partial, term in
                if label == term { return partial + 5.0 }
                if label.contains(term) || term.contains(label) { return partial + 3.0 }
                return partial + 1.5
            }
            return (candidate, matched, candidate.score + specificity)
        }
        guard let best = scored.max(by: { left, right in left.2 < right.2 }) else {
            return nil
        }
        return (best.0, best.1)
    }

    private func bestDoorDashModifierCandidate(
        in candidates: [WebsiteC2ACandidate],
        targetTerms: [String],
        preferredGroup: DoorDashCustomizerGroupKind = .unknown
    ) -> (candidate: WebsiteC2ACandidate, matched: [String])? {
        let relevant = candidates.filter { $0.role == "dd_modifier_option" && !$0.blocked }
        guard !relevant.isEmpty else {
            return nil
        }
        let scored = relevant.compactMap { candidate -> (WebsiteC2ACandidate, [String], Double)? in
            let matched = candidateMatchedModifierTerms(candidate, targetTerms: targetTerms)
            guard !matched.isEmpty else { return nil }
            let label = normalizedCommerceTerm(candidate.label)
            let groupKind = doorDashGroupKind(for: candidate)
            let specificity = matched.reduce(0.0) { partial, term in
                if label == term { return partial + 6.0 }
                if label.contains(term) || term.contains(label) { return partial + 4.0 }
                return partial + 2.0
            }
            let groupBonus = preferredGroup != .unknown && groupKind == preferredGroup ? 16.0 : 0.0
            return (candidate, matched, candidate.score + specificity + groupBonus)
        }
        guard let best = scored.max(by: { left, right in left.2 < right.2 }) else {
            return nil
        }
        return (best.0, best.1)
    }

    private func shouldSaveAfterModifierSelection(
        saveCandidate: WebsiteC2ACandidate?,
        requestedTerms: [String],
        activeGroup: DoorDashCustomizerGroupKind,
        activeGroupRequired: Bool,
        preservedGroups: Set<DoorDashCustomizerGroupKind>
    ) -> Bool {
        guard saveCandidate != nil else {
            return false
        }
        let recentLabel = normalizedCommerceTerm(lastModifierSelectionLabel)
        guard !recentLabel.isEmpty else {
            return false
        }
        let recentGroup = doorDashGroupKind(from: lastModifierSelectionGroupKey)
        if preservedGroups.contains(recentGroup) {
            return false
        }
        if activeGroupRequired, activeGroup != .unknown, recentGroup != activeGroup {
            return false
        }
        guard Date().timeIntervalSince(lastModifierSelectionAt) < 4.0 else {
            return false
        }
        return !requestedTerms.contains(where: { term in
            recentLabel == term || recentLabel.contains(term) || term.contains(recentLabel)
        })
    }

    private func fallbackDoorDashModifierCandidate(
        in candidates: [WebsiteC2ACandidate],
        activeGroup: DoorDashCustomizerGroupKind = .unknown,
        disallowedGroups: Set<DoorDashCustomizerGroupKind> = []
    ) -> WebsiteC2ACandidate? {
        let ignoredLabels = Set([
            "choose your size",
            "topping side",
            "user preferences",
            "preferences",
            "required",
            "optional",
        ])
        if activeGroup == .toppingSide,
           let whole = candidates.first(where: {
               $0.role == "dd_modifier_option"
                   && !$0.blocked
                   && !disallowedGroups.contains(doorDashGroupKind(for: $0))
                   && normalizedCommerceTerm($0.label) == "whole"
           }) {
            return whole
        }
        if activeGroup != .unknown,
           let groupScoped = candidates.first(where: { candidate in
               candidate.role == "dd_modifier_option"
                   && !candidate.blocked
                   && doorDashGroupKind(for: candidate) == activeGroup
                   && !disallowedGroups.contains(doorDashGroupKind(for: candidate))
                   && !ignoredLabels.contains(normalizedCommerceTerm(candidate.label))
           }) {
            return groupScoped
        }
        return candidates.first { candidate in
            guard candidate.role == "dd_modifier_option", !candidate.blocked else {
                return false
            }
            if disallowedGroups.contains(doorDashGroupKind(for: candidate)) {
                return false
            }
            let label = normalizedCommerceTerm(candidate.label)
            guard !label.isEmpty, !ignoredLabels.contains(label) else {
                return false
            }
            return true
        }
    }

    private func finalizePendingFoodAdd() {
        if pendingFoodAddOperation == "primary" {
            primaryFoodItemAdded = true
            inProgressPrimaryItemLabel = ""
            preferCartProgress = pendingFoodAddOns.isEmpty
        } else if pendingFoodAddOperation == "addon" {
            if !pendingFoodAddOns.isEmpty {
                pendingFoodAddOns.removeFirst()
            }
            preferCartProgress = pendingFoodAddOns.isEmpty
        }
        pendingDoorDashRole = ""
        pendingDoorDashLabel = ""
        addToCartRetryCount = 0
        pendingFoodAddOperation = ""
        inFlightModifierTerms = []
        doorDashModifierCommitPending = false
        doorDashPendingCommitKind = ""
        doorDashReviewBridgePending = false
        lastModifierSelectionLabel = ""
        lastModifierSelectionGroupKey = ""
        lastModifierSelectionAt = .distantPast
        traversedDoorDashDerivedGroups = []
        pendingStepActionRole = ""
        pendingStepActionLabel = ""
        pendingStepTargetGroupKey = ""
        pendingStepTargetGroupLabel = ""
        pendingStepTargetTapFingerprint = ""
        pendingStepTargetOpensSubflow = false
        pendingStepActionSignature = ""
        pendingStepActionAt = .distantPast
        pendingStepTapAcknowledged = false
        pendingStepTapVerifiedSelection = false
        pendingStepObservedGroupKey = ""
        pendingStepObservedGroupLabel = ""
        pendingStepObservedCheckedRadioCount = 0
        pendingStepObservedCheckedCheckboxCount = 0
        pendingStepConsumedTerms = []
        pendingStepCommitKind = ""
        pendingStepTapRetryCount = 0
    }

    private func clearPendingStepAction() {
        pendingStepActionRole = ""
        pendingStepActionLabel = ""
        pendingStepTargetGroupKey = ""
        pendingStepTargetGroupLabel = ""
        pendingStepTargetTapFingerprint = ""
        pendingStepTargetOpensSubflow = false
        pendingStepActionSignature = ""
        pendingStepActionAt = .distantPast
        pendingStepTapAcknowledged = false
        pendingStepTapVerifiedSelection = false
        pendingStepObservedGroupKey = ""
        pendingStepObservedGroupLabel = ""
        pendingStepObservedCheckedRadioCount = 0
        pendingStepObservedCheckedCheckboxCount = 0
        pendingStepConsumedTerms = []
        pendingStepCommitKind = ""
        pendingStepTapRetryCount = 0
    }

    private func recordPendingDoorDashStep(
        role: String,
        label: String,
        candidate: WebsiteC2ACandidate?,
        signature: String,
        state: WebsiteC2AState,
        consumedTerms: Set<String>,
        commitKind: String
    ) {
        if role != "dd_modifier_save" {
            doorDashReviewBridgePending = false
        }
        pendingStepActionRole = role
        pendingStepActionLabel = label
        pendingStepTargetGroupKey = candidate?.groupKey ?? ""
        pendingStepTargetGroupLabel = candidate?.groupLabel ?? ""
        pendingStepTargetTapFingerprint = candidate?.tapFingerprint ?? ""
        pendingStepTargetOpensSubflow = candidate?.opensSubflow ?? false
        pendingStepActionSignature = signature
        pendingStepActionAt = Date()
        pendingStepTapAcknowledged = false
        pendingStepTapVerifiedSelection = false
        pendingStepObservedGroupKey = state.serviceFacts["dd_active_group_key"] ?? ""
        pendingStepObservedGroupLabel = state.serviceFacts["dd_active_group_label"] ?? ""
        pendingStepObservedCheckedRadioCount = doorDashFactInt(state, key: "dd_checked_radio_count")
        pendingStepObservedCheckedCheckboxCount = doorDashFactInt(state, key: "dd_checked_checkbox_count")
        pendingStepConsumedTerms = consumedTerms
        pendingStepCommitKind = commitKind
        pendingStepTapRetryCount = 0
    }

    private func matchingPendingDoorDashModifierCandidate(in state: WebsiteC2AState) -> WebsiteC2ACandidate? {
        let targetLabel = normalizedCommerceTerm(pendingStepActionLabel)
        let targetGroupKey = pendingStepTargetGroupKey
        let targetGroupLabel = normalizedCommerceTerm(pendingStepTargetGroupLabel)
        let targetFingerprint = normalizedCommerceTerm(pendingStepTargetTapFingerprint)
        let observedGroupLabel = normalizedCommerceTerm(pendingStepObservedGroupLabel)
        return state.candidates.first { candidate in
            guard candidate.role == "dd_modifier_option", !candidate.blocked else {
                return false
            }
            guard normalizedCommerceTerm(candidate.label) == targetLabel else {
                return false
            }
            if !targetFingerprint.isEmpty,
               normalizedCommerceTerm(candidate.tapFingerprint) == targetFingerprint {
                return true
            }
            if !targetGroupKey.isEmpty, candidate.groupKey == targetGroupKey {
                return true
            }
            if !targetGroupLabel.isEmpty, normalizedCommerceTerm(candidate.groupLabel) == targetGroupLabel {
                return true
            }
            if !pendingStepObservedGroupKey.isEmpty, candidate.groupKey == pendingStepObservedGroupKey {
                return true
            }
            if !observedGroupLabel.isEmpty, normalizedCommerceTerm(candidate.groupLabel) == observedGroupLabel {
                return true
            }
            return pendingStepObservedGroupKey.isEmpty
                && observedGroupLabel.isEmpty
                && targetGroupKey.isEmpty
                && targetGroupLabel.isEmpty
                && targetFingerprint.isEmpty
        }
    }

    private func pendingDoorDashRetryCandidate(in state: WebsiteC2AState) -> WebsiteC2ACandidate? {
        switch pendingStepActionRole {
        case "dd_modifier_option":
            if let matched = matchingPendingDoorDashModifierCandidate(in: state) {
                return matched
            }
            let targetLabel = normalizedCommerceTerm(pendingStepActionLabel)
            return state.candidates.first {
                $0.role == "dd_modifier_option"
                    && !$0.blocked
                    && normalizedCommerceTerm($0.label) == targetLabel
            }
        case "dd_modifier_save":
            return state.candidates.first { $0.role == "dd_modifier_save" && !$0.blocked }
        default:
            return nil
        }
    }

    private func pendingDoorDashStepConfirmed(in state: WebsiteC2AState, signature: String) -> Bool {
        switch pendingStepActionRole {
        case "dd_modifier_option":
            let activeGroupKey = state.serviceFacts["dd_active_group_key"] ?? ""
            let activeGroupLabel = normalizedCommerceTerm(state.serviceFacts["dd_active_group_label"] ?? "")
            let targetGroupKey = pendingStepTargetGroupKey
            let targetGroupLabel = normalizedCommerceTerm(pendingStepTargetGroupLabel)
            let previousGroupLabel = normalizedCommerceTerm(pendingStepObservedGroupLabel)
            let changedFromTargetGroup = (!targetGroupKey.isEmpty && !activeGroupKey.isEmpty && activeGroupKey != targetGroupKey)
                || (!targetGroupLabel.isEmpty && !activeGroupLabel.isEmpty && activeGroupLabel != targetGroupLabel)
            let changedFromObservedGroup = (!pendingStepObservedGroupKey.isEmpty && !activeGroupKey.isEmpty && activeGroupKey != pendingStepObservedGroupKey)
                || (!previousGroupLabel.isEmpty && !activeGroupLabel.isEmpty && activeGroupLabel != previousGroupLabel)
            let advancedSubflow = pendingStepTapAcknowledged
                && pendingStepTargetOpensSubflow
                && signature != pendingStepActionSignature
                && (changedFromTargetGroup || changedFromObservedGroup)
            if pendingStepCommitKind == "requested" {
                if let candidate = matchingPendingDoorDashModifierCandidate(in: state), candidate.isSelected {
                    return true
                }
                if pendingStepTapVerifiedSelection {
                    return true
                }
                return advancedSubflow
            }
            if let candidate = matchingPendingDoorDashModifierCandidate(in: state), candidate.isSelected {
                if !pendingStepTargetOpensSubflow || advancedSubflow {
                    return true
                }
            }
            if !pendingStepObservedGroupKey.isEmpty, !activeGroupKey.isEmpty, activeGroupKey != pendingStepObservedGroupKey {
                return true
            }
            if !previousGroupLabel.isEmpty, !activeGroupLabel.isEmpty, activeGroupLabel != previousGroupLabel, signature != pendingStepActionSignature {
                return true
            }
            let checkedRadioCount = doorDashFactInt(state, key: "dd_checked_radio_count")
            let checkedCheckboxCount = doorDashFactInt(state, key: "dd_checked_checkbox_count")
            return checkedRadioCount > pendingStepObservedCheckedRadioCount
                || checkedCheckboxCount > pendingStepObservedCheckedCheckboxCount
        case "dd_modifier_save":
            if state.pageKind != "dd_item_modal" {
                return true
            }
            if !state.candidates.contains(where: { $0.role == "dd_modifier_save" && !$0.blocked }) {
                return true
            }
            let activeGroupKey = state.serviceFacts["dd_active_group_key"] ?? ""
            if !pendingStepObservedGroupKey.isEmpty, !activeGroupKey.isEmpty, activeGroupKey != pendingStepObservedGroupKey {
                return true
            }
            return state.candidates.contains(where: { $0.role == "dd_add_to_cart" && !$0.blocked })
        default:
            return false
        }
    }

    private func applyPendingDoorDashStepSuccess() {
        switch pendingStepActionRole {
        case "dd_modifier_option":
            if !pendingStepConsumedTerms.isEmpty {
                inFlightModifierTerms.formUnion(pendingStepConsumedTerms)
            }
            doorDashModifierCommitPending = true
            doorDashPendingCommitKind = pendingStepCommitKind
            if pendingStepCommitKind == "prerequisite",
               pendingStepTargetOpensSubflow {
                let traversedGroup = doorDashGroupKind(from: pendingStepTargetGroupKey)
                if traversedGroup != .unknown {
                    traversedDoorDashDerivedGroups.insert(traversedGroup)
                }
            }
            lastModifierSelectionLabel = pendingStepActionLabel
            lastModifierSelectionGroupKey = pendingStepTargetGroupKey
            lastModifierSelectionAt = Date()
        case "dd_modifier_save":
            if !inFlightModifierTerms.isEmpty {
                completedModifierTerms.formUnion(inFlightModifierTerms)
                inFlightModifierTerms.removeAll()
            }
            doorDashModifierCommitPending = false
            doorDashPendingCommitKind = ""
            lastModifierSelectionLabel = ""
            lastModifierSelectionGroupKey = ""
            lastModifierSelectionAt = .distantPast
        default:
            break
        }
    }

    private func rollbackPendingDoorDashStepFailure() {
        if pendingStepActionRole == "dd_modifier_save" {
            // Save never committed, so preserve the in-flight constraint and keep the commit boundary active.
            doorDashModifierCommitPending = !inFlightModifierTerms.isEmpty || doorDashModifierCommitPending
        }
        clearPendingStepAction()
    }

    private var browserToolbar: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Button {
                    browser.goBack()
                } label: {
                    Image(systemName: "chevron.left")
                }
                .disabled(!browser.canGoBack)

                Button {
                    browser.goForward()
                } label: {
                    Image(systemName: "chevron.right")
                }
                .disabled(!browser.canGoForward)

                Button {
                    browser.reload()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }

                Button(browser.isInspecting ? "Inspecting..." : "Inspect") {
                    isC2AConsoleClosed = false
                    browser.inspectPage(capsule: route.capsule)
                }
                .disabled(browser.isInspecting || browser.isLoading)

                Button("Send Debug") {
                    sendBrowserDebugSnapshot(reason: "manual_toolbar", state: browser.websiteState, force: true)
                }
                .disabled(browser.currentURL.isEmpty)

                Spacer()

                if let url = URL(string: browser.currentURL), !browser.currentURL.isEmpty {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
            }
            Text(browser.pageTitle)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
            if !browser.currentURL.isEmpty {
                Text(browser.currentURL)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color(.systemBackground))
    }

    private var websiteC2AConsole: some View {
        VStack(alignment: .leading, spacing: 8) {
            Capsule()
                .fill(Color.secondary.opacity(0.35))
                .frame(width: 36, height: 4)
                .frame(maxWidth: .infinity)
                .padding(.top, 2)

            HStack(spacing: 8) {
                Text("Memla's Mirror")
                    .font(.caption.weight(.semibold))
                Spacer()
                if !browser.inspectionStatus.isEmpty {
                    Text(browser.inspectionStatus)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Button(isC2AConsoleExpanded ? "Hide" : "Open") {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        isC2AConsoleExpanded.toggle()
                    }
                }
                .buttonStyle(.bordered)
                .font(.caption2)
                if let state = browser.websiteState {
                    Button("Copy Debug") {
                        copyDebugSnapshot(state)
                    }
                    .buttonStyle(.bordered)
                    .font(.caption2)
                    Button("Send Debug") {
                        sendBrowserDebugSnapshot(reason: "manual_console", state: state, force: true)
                    }
                    .buttonStyle(.bordered)
                    .font(.caption2)
                    if !agencyTrace.isEmpty {
                        Button("Copy Trace") {
                            copyAgencyTrace()
                        }
                        .buttonStyle(.bordered)
                        .font(.caption2)
                    }
                }
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        isC2AConsoleClosed = true
                    }
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.bordered)
                .font(.caption2)
            }

            if let state = browser.websiteState {
                if isC2AConsoleExpanded {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 10) {
                            mirrorCompactContent(for: state)
                            if !agencyTrace.isEmpty {
                                Divider()
                                VStack(alignment: .leading, spacing: 4) {
                                    Text("Agency Trace")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(.secondary)
                                    ForEach(Array(agencyTrace.prefix(10).enumerated()), id: \.offset) { _, entry in
                                        Text(entry)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                }
                            }
                            Divider()
                            Text("Raw Website C2A")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            expandedWebsiteC2AContent(for: state)
                        }
                    }
                    .frame(maxHeight: 360)
                } else {
                    mirrorCompactContent(for: state)
                }
            } else if !browser.inspectionStatus.isEmpty {
                Text(browser.inspectionStatus)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            if !debugCopyStatus.isEmpty {
                Text(debugCopyStatus)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if !debugUploadStatus.isEmpty {
                Text(debugUploadStatus)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color(.systemBackground), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .shadow(color: Color.black.opacity(0.16), radius: 18, x: 0, y: -6)
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
    }

    private func mirrorCompactContent(for state: WebsiteC2AState) -> some View {
        let step = guidedStep(for: state)
        let candidates = mirrorCandidates(for: state)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: mirrorIcon(for: state))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(mirrorColor(for: state))
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 3) {
                    Text(mirrorTitle(for: state))
                        .font(.caption.weight(.semibold))
                    Text(mirrorSummary(for: state, step: step))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                Spacer(minLength: 0)
            }
            if (state.pageKind.hasPrefix("dd_") || state.pageKind.hasPrefix("ue_") || state.pageKind.hasPrefix("ub_")), !autoDriveStatus.isEmpty {
                Label(autoDriveStatus, systemImage: autoDriveEnabled ? "bolt.fill" : "hand.tap.fill")
                    .font(.caption2)
                    .foregroundStyle(autoDriveEnabled ? .green : .orange)
                    .lineLimit(2)
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(mirrorFacts(for: state)) { fact in
                        capsuleChip(title: fact.title, value: fact.value)
                    }
                }
            }
            if !candidates.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 8) {
                        ForEach(Array(candidates.prefix(3))) { candidate in
                            mirrorCandidateCard(candidate)
                        }
                    }
                }
            }
            if let verification = state.capsuleVerification, (state.pageKind == "cart" || state.pageKind == "checkout" || state.pageKind == "ue_cart_page" || state.pageKind == "ue_checkout") {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Mirror Verification")
                        .font(.caption.weight(.semibold))
                    Text(verification.summary)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                .padding(8)
                .background(Color.blue.opacity(0.10), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }

    private func mirrorPrimarySurface(for state: WebsiteC2AState) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                mirrorSectionCard(title: "Memla's Mirror", systemImage: mirrorIcon(for: state)) {
                    mirrorCompactContent(for: state)
                }

                mirrorSectionCard(title: "Next Move", systemImage: "point.topleft.down.curvedto.point.bottomright.up") {
                    guidedStepControls(for: state)
                    HStack(spacing: 8) {
                        Button(browser.isInspecting ? "Inspecting..." : "Refresh Mirror") {
                            browser.inspectPage(capsule: route.capsule)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(browser.isInspecting || browser.isLoading)

                        Button(isRawPageVisible ? "Hide Raw Page" : "Show Raw Page") {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                isRawPageVisible.toggle()
                            }
                        }
                        .buttonStyle(.bordered)
                    }
                }

                if state.authState == "login_required" || state.authState == "likely_signed_in" {
                    mirrorSectionCard(title: "Session", systemImage: "person.badge.key") {
                        authBridgeControls(for: state)
                    }
                }

                if !mirrorItemCandidates(for: state).isEmpty {
                    mirrorSectionCard(title: mirrorItemSectionTitle(for: state), systemImage: "square.grid.2x2") {
                        mirrorCandidateScroller(mirrorItemCandidates(for: state))
                    }
                }

                if !mirrorControlCandidates(for: state).isEmpty {
                    mirrorSectionCard(title: "Mirror Controls", systemImage: "slider.horizontal.3") {
                        mirrorCandidateScroller(mirrorControlCandidates(for: state))
                    }
                }

                if let verification = state.capsuleVerification {
                    mirrorSectionCard(title: (state.pageKind == "checkout" || state.pageKind == "ue_checkout") ? "Final Review" : "Checkpoint Verification", systemImage: (state.pageKind == "checkout" || state.pageKind == "ue_checkout") ? "hand.raised.fill" : "checklist") {
                        capsuleVerificationControls(for: state)
                        if !verification.missing.isEmpty {
                            Text("Still missing: \(verification.missing.map { readableRequirement($0) }.joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                                .lineLimit(3)
                        }
                    }
                }

                if !bridgeSuggestions(for: state).isEmpty {
                    mirrorSectionCard(title: "Recovery Bridges", systemImage: "arrow.triangle.branch") {
                        bridgeSuggestionControls(for: state)
                    }
                }

                if searchQueryIfAvailable(for: state) != nil {
                    mirrorSectionCard(title: "Search Primitive", systemImage: "magnifyingglass") {
                        searchActionControls(for: state)
                    }
                }
            }
            .padding(12)
        }
        .background(Color(.systemGroupedBackground))
    }

    private func expandedWebsiteC2AContent(for state: WebsiteC2AState) -> some View {
        VStack(alignment: .leading, spacing: 8) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        capsuleChip(title: "Page", value: readableRequirement(state.pageKind))
                        capsuleChip(title: "Inputs", value: "\(state.inputs.count)")
                        capsuleChip(title: "Buttons", value: "\(state.buttons.count)")
                        capsuleChip(title: "Links", value: "\(state.links.count)")
                        capsuleChip(title: "Candidates", value: "\(state.candidates.count)")
                        capsuleChip(title: "Auth", value: readableRequirement(state.authState))
                    }
                }
                Text(state.summary)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                if !state.safeActions.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Array(state.safeActions.prefix(6)), id: \.self) { action in
                                Label(readableRequirement(action), systemImage: "checkmark.shield")
                                    .font(.caption2)
                                    .padding(.horizontal, 9)
                                    .padding(.vertical, 6)
                                    .background(Color.green.opacity(0.12), in: Capsule())
                            }
                        }
                    }
                }
                guidedStepControls(for: state)
                authBridgeControls(for: state)
                capsuleVerificationControls(for: state)
                candidateControls(for: state)
                if !state.residuals.isEmpty {
                    Text("Residuals: \(state.residuals.map { readableRequirement($0) }.joined(separator: ", "))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                searchActionControls(for: state)
                bridgeSuggestionControls(for: state)
                if !state.headings.isEmpty {
                    Text("Headings: \(state.headings.prefix(3).joined(separator: " / "))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
        }
    }

    private func mirrorCandidates(for state: WebsiteC2AState) -> [WebsiteC2ACandidate] {
        let deprioritizedRoles = Set(["review_link", "accessibility_link", "utility_link", "auth_link", "nav_link", "dd_menu_nav"])
        let preferredRoles = Set(["store_link", "menu_item", "item_action_button", "cart_link", "cart_button", "control_button", "checkout_button", "dd_store_card", "dd_item_card", "dd_modifier_option", "dd_modifier_save", "dd_add_to_cart", "dd_continue_cta", "dd_cart_cta", "dd_tip_option", "dd_address_cta", "dd_modal_close", "ue_continue_browser", "ue_address_cta", "ue_address_result", "ue_search_entry", "ue_store_card", "ue_item_card", "ue_add_to_cart", "ue_cart_cta", "ue_continue_cta", "ue_modal_close", "ub_pickup_input", "ub_pickup_current_location", "ub_pickup_result", "ub_dropoff_input", "ub_dropoff_result", "ub_see_prices_cta", "ub_vehicle_option"])
        let visibleCandidates = state.candidates.filter { !deprioritizedRoles.contains($0.role) && !$0.blocked }
        let stateScopedRoles: Set<String>
        switch state.pageKind {
        case "ub_trip_builder":
            stateScopedRoles = ["ub_pickup_current_location", "ub_pickup_result", "ub_pickup_input", "ub_dropoff_result", "ub_dropoff_input", "ub_see_prices_cta"]
        case "ub_product_selection":
            stateScopedRoles = ["ub_vehicle_option"]
        case "ue_entry_gate":
            stateScopedRoles = ["ue_continue_browser", "ue_address_cta", "ue_address_result", "ue_search_entry"]
        case "ue_search_results":
            stateScopedRoles = ["ue_store_card"]
        case "ue_storefront":
            stateScopedRoles = ["ue_item_card", "ue_add_to_cart", "ue_cart_cta"]
        case "ue_item_modal":
            stateScopedRoles = ["ue_add_to_cart", "ue_item_card", "ue_modal_close"]
        case "ue_cart_page":
            stateScopedRoles = ["ue_continue_cta", "ue_cart_cta", "ue_modal_close"]
        case "dd_search_results":
            stateScopedRoles = ["dd_store_card", "dd_cart_cta"]
        case "dd_storefront":
            stateScopedRoles = ["dd_item_card", "dd_add_to_cart", "dd_cart_cta"]
        case "dd_item_modal":
            stateScopedRoles = ["dd_modifier_option", "dd_modifier_save", "dd_add_to_cart", "dd_cart_cta", "dd_modal_close"]
        case "dd_cart_drawer", "dd_cart_page":
            stateScopedRoles = ["dd_cart_cta", "dd_continue_cta", "dd_tip_option", "dd_address_cta", "dd_modal_close"]
        case "dd_checkout":
            stateScopedRoles = ["dd_tip_option", "dd_address_cta", "dd_modal_close"]
        case "dd_payment_sheet":
            stateScopedRoles = ["dd_modal_close"]
        default:
            stateScopedRoles = preferredRoles
        }
        let stateScoped = visibleCandidates.filter { candidate in
            stateScopedRoles.contains(candidate.role)
        }
        let candidatePool = stateScoped.isEmpty ? visibleCandidates : stateScoped
        let focusedPool: [WebsiteC2ACandidate]
        if state.pageKind == "dd_item_modal" {
            focusedPool = focusedDoorDashItemModalCandidates(from: candidatePool, state: state)
        } else {
            focusedPool = candidatePool
        }
        let preferred = focusedPool.filter { candidate in
            candidate.score > 0 || preferredRoles.contains(candidate.role)
        }
        let effectivePool = preferred.isEmpty ? focusedPool : preferred
        let sorted = effectivePool.sorted { left, right in
            let leftPriority = mirrorRolePriority(pageKind: state.pageKind, role: left.role)
            let rightPriority = mirrorRolePriority(pageKind: state.pageKind, role: right.role)
            if leftPriority != rightPriority {
                return leftPriority > rightPriority
            }
            if left.score != right.score {
                return left.score > right.score
            }
            return left.label.localizedCaseInsensitiveCompare(right.label) == .orderedAscending
        }
        let limit: Int
        switch state.pageKind {
        case "dd_storefront", "dd_item_modal", "ue_storefront", "ue_item_modal":
            limit = 12
        case "dd_search_results", "ue_search_results":
            limit = 8
        default:
            limit = 4
        }
        return Array(sorted.prefix(limit))
    }

    private func mirrorRolePriority(pageKind: String, role: String) -> Int {
        switch pageKind {
        case "ub_trip_builder":
            switch role {
            case "ub_pickup_result":
                return 100
            case "ub_pickup_input":
                return 96
            case "ub_pickup_current_location":
                return 90
            case "ub_dropoff_result":
                return 88
            case "ub_dropoff_input":
                return 84
            case "ub_see_prices_cta":
                return 80
            default:
                return 12
            }
        case "ub_product_selection":
            switch role {
            case "ub_vehicle_option":
                return 100
            default:
                return 10
            }
        case "ue_entry_gate":
            switch role {
            case "ue_continue_browser":
                return 100
            case "ue_address_result":
                return 95
            case "ue_address_cta":
                return 85
            case "ue_search_entry":
                return 70
            default:
                return 10
            }
        case "ue_search_results":
            switch role {
            case "ue_store_card":
                return 100
            default:
                return 10
            }
        case "ue_storefront":
            switch role {
            case "ue_item_card":
                return 100
            case "ue_add_to_cart":
                return 85
            case "ue_cart_cta":
                return 75
            default:
                return 10
            }
        case "ue_item_modal":
            switch role {
            case "ue_add_to_cart":
                return 100
            case "ue_item_card":
                return 70
            case "ue_modal_close":
                return 10
            default:
                return 12
            }
        case "ue_cart_page":
            switch role {
            case "ue_continue_cta":
                return 100
            case "ue_cart_cta":
                return 70
            case "ue_modal_close":
                return 10
            default:
                return 12
            }
        case "dd_search_results":
            switch role {
            case "dd_store_card":
                return 100
            case "dd_cart_cta":
                return 85
            default:
                return 10
            }
        case "dd_storefront":
            switch role {
            case "dd_item_card":
                return 100
            case "dd_add_to_cart":
                return 90
            case "dd_cart_cta":
                return 70
            case "dd_modal_close":
                return 5
            default:
                return 10
            }
        case "dd_item_modal":
            switch role {
            case "dd_modifier_save":
                return 110
            case "dd_modifier_option":
                return 100
            case "dd_add_to_cart":
                return 85
            case "dd_cart_cta":
                return 70
            case "dd_item_card":
                return 60
            case "dd_modal_close":
                return 10
            default:
                return 15
            }
        case "dd_cart_drawer", "dd_cart_page":
            switch role {
            case "dd_continue_cta":
                return 100
            case "dd_cart_cta":
                return 70
            case "dd_tip_option":
                return 60
            case "dd_address_cta":
                return 50
            case "dd_modal_close":
                return 5
            default:
                return 10
            }
        case "dd_checkout":
            switch role {
            case "dd_tip_option":
                return 100
            case "dd_address_cta":
                return 90
            case "dd_modal_close":
                return 10
            default:
                return 15
            }
        default:
            return 10
        }
    }

    private enum DoorDashCustomizerGroupKind: String {
        case size
        case crust
        case topping
        case toppingSide = "topping_side"
        case preferences
        case review
        case unknown
    }

    private enum DoorDashCustomizerFocusKind {
        case requestedModifier
        case prerequisiteModifier
        case saveStep
        case reviewStep
        case waiting
    }

    private struct DoorDashCustomizerSnapshot {
        let focusKind: DoorDashCustomizerFocusKind
        let activeGroupKind: DoorDashCustomizerGroupKind
        let activeGroupLabel: String
        let activeGroupRequired: Bool
        let activeGroupResolved: Bool
        let stage: FoodModifierStage
        let remainingTerms: [String]
        let requestedTerms: [String]
        let preservedGroups: Set<DoorDashCustomizerGroupKind>
        let traversedDerivedGroups: Set<DoorDashCustomizerGroupKind>
        let focusLabel: String
        let targetCandidate: WebsiteC2ACandidate?
        let prerequisiteCandidate: WebsiteC2ACandidate?
        let saveCandidate: WebsiteC2ACandidate?
        let addCandidate: WebsiteC2ACandidate?
        let filteredCandidates: [WebsiteC2ACandidate]
        let addToCartAllowed: Bool
        let finalReviewBridgeActive: Bool
    }

    private func shouldBridgeDoorDashReviewAfterSaveFailure(status: String, state: WebsiteC2AState?) -> Bool {
        guard pendingStepActionRole == "dd_modifier_save",
              let state,
              state.pageKind == "dd_item_modal" else {
            return false
        }
        let lowered = status.lowercased()
        guard lowered.contains("doordash modifier save not found") || lowered.contains("save tap blocked: doordash modifier save not found") else {
            return false
        }
        let modifierTargets = currentModifierTargets()
        return modifierTargets.terms.isEmpty && inFlightModifierTerms.isEmpty
    }

    private func doorDashCustomizerSnapshot(from candidates: [WebsiteC2ACandidate], state: WebsiteC2AState) -> DoorDashCustomizerSnapshot {
        let modifierTargets = currentModifierTargets()
        let remainingModifierTerms = modifierTargets.terms
        let requestedModifierTerms = allRequestedModifierTerms()
        let detectedActiveGroupKind = doorDashActiveGroupKind(from: state, candidates: candidates)
        let detectedActiveGroupLabel = doorDashActiveGroupLabel(from: state, candidates: candidates)
        let detectedActiveGroupRequired = state.serviceFacts["dd_active_group_required"] == "true"
        let preservedGroups = preservedDoorDashGroupKinds(for: modifierTargets.stage)
        let traversedDerivedGroups = traversedDoorDashDerivedGroups
        let protectedGroups = preservedGroups.union(traversedDerivedGroups)
        let unresolvedRequiredGroup = unresolvedRequiredDoorDashGroup(
            in: candidates,
            traversedDerivedGroups: traversedDerivedGroups,
            excluding: protectedGroups
        )
        var saveCandidate = candidates.first(where: { $0.role == "dd_modifier_save" && !$0.blocked })
        var addCandidate: WebsiteC2ACandidate?
        if let existingAddCandidate = candidates.first(where: { $0.role == "dd_add_to_cart" && !$0.blocked }) {
            addCandidate = existingAddCandidate
        } else if state.serviceFacts["dd_has_add_to_cart"] == "true" {
            let label = state.serviceFacts["dd_add_to_cart_label"] ?? "Add to cart"
            addCandidate = WebsiteC2ACandidate(
                id: "synthetic-dd-item-modal-add-to-cart",
                domIndex: -1,
                label: label,
                url: "",
                kind: "button",
                role: "dd_add_to_cart",
                score: 5.1,
                matchedTerms: [],
                blocked: false,
                tapSafety: "caution",
                tapReason: "Needs user review before Memla taps",
                reason: "DoorDash add-to-cart control",
                groupKey: DoorDashCustomizerGroupKind.review.rawValue,
                groupLabel: "Add to cart",
                groupRequired: false,
                tapFingerprint: "dd_add_to_cart | review | add to cart | add to cart"
            )
        } else {
            addCandidate = nil
        }
        let finalReviewBridgeActive = doorDashReviewBridgePending
            && remainingModifierTerms.isEmpty
            && inFlightModifierTerms.isEmpty
        if finalReviewBridgeActive {
            if addCandidate == nil {
                let label = state.serviceFacts["dd_add_to_cart_label"] ?? "Add to cart"
                addCandidate = WebsiteC2ACandidate(
                    id: "bridged-dd-item-modal-add-to-cart",
                    domIndex: -1,
                    label: label,
                    url: "",
                    kind: "button",
                    role: "dd_add_to_cart",
                    score: 5.3,
                    matchedTerms: [],
                    blocked: false,
                    tapSafety: "caution",
                    tapReason: "Needs user review before Memla taps",
                    reason: "DoorDash review CTA after final customizer save",
                    groupKey: DoorDashCustomizerGroupKind.review.rawValue,
                    groupLabel: "Add to cart",
                    groupRequired: false,
                    tapFingerprint: "dd_add_to_cart | review | add to cart | add to cart"
                )
            }
            saveCandidate = nil
        }
        let initialTargetCandidate = bestDoorDashModifierCandidate(
            in: candidates,
            targetTerms: remainingModifierTerms,
            preferredGroup: detectedActiveGroupKind
        )?.candidate
        let preferredGroups = preferredDoorDashGroupKinds(for: modifierTargets.stage)
        let activeGroupKind: DoorDashCustomizerGroupKind
        let activeGroupLabel: String
        let activeGroupRequired: Bool
        if let initialTargetCandidate {
            let targetGroupKind = doorDashGroupKind(for: initialTargetCandidate)
            if targetGroupKind != .unknown, preferredGroups.contains(targetGroupKind), targetGroupKind != detectedActiveGroupKind {
                activeGroupKind = targetGroupKind
                activeGroupLabel = initialTargetCandidate.groupLabel.isEmpty ? detectedActiveGroupLabel : initialTargetCandidate.groupLabel
                activeGroupRequired = unresolvedRequiredGroup?.kind == targetGroupKind
                    || (detectedActiveGroupKind == targetGroupKind && detectedActiveGroupRequired)
            } else if let unresolvedRequiredGroup,
                      unresolvedRequiredGroup.kind != .unknown,
                      (detectedActiveGroupKind == .unknown
                        || preservedGroups.contains(detectedActiveGroupKind)
                        || !detectedActiveGroupRequired) {
                activeGroupKind = unresolvedRequiredGroup.kind
                activeGroupLabel = unresolvedRequiredGroup.label.isEmpty ? detectedActiveGroupLabel : unresolvedRequiredGroup.label
                activeGroupRequired = true
            } else {
                activeGroupKind = detectedActiveGroupKind
                activeGroupLabel = detectedActiveGroupLabel
                activeGroupRequired = detectedActiveGroupRequired
            }
        } else if let unresolvedRequiredGroup,
                  unresolvedRequiredGroup.kind != .unknown,
                  (detectedActiveGroupKind == .unknown
                    || preservedGroups.contains(detectedActiveGroupKind)
                    || !detectedActiveGroupRequired) {
            activeGroupKind = unresolvedRequiredGroup.kind
            activeGroupLabel = unresolvedRequiredGroup.label.isEmpty ? detectedActiveGroupLabel : unresolvedRequiredGroup.label
            activeGroupRequired = true
        } else {
            activeGroupKind = detectedActiveGroupKind
            activeGroupLabel = detectedActiveGroupLabel
            activeGroupRequired = detectedActiveGroupRequired
        }
        let selectedActiveCandidate = selectedDoorDashModifierCandidate(in: candidates, group: activeGroupKind)
        let activeGroupResolved: Bool
        if activeGroupRequired, let selectedActiveCandidate {
            if selectedActiveCandidate.opensSubflow {
                activeGroupResolved = traversedDerivedGroups.contains(activeGroupKind)
            } else {
                activeGroupResolved = true
            }
        } else {
            activeGroupResolved = false
        }
        let targetCandidate = bestDoorDashModifierCandidate(
            in: candidates,
            targetTerms: remainingModifierTerms,
            preferredGroup: activeGroupKind
        )?.candidate
        let prerequisiteCandidate: WebsiteC2ACandidate?
        if activeGroupRequired {
            if let selectedActiveCandidate,
               selectedActiveCandidate.opensSubflow,
               !traversedDerivedGroups.contains(activeGroupKind) {
                prerequisiteCandidate = selectedActiveCandidate
            } else if activeGroupResolved {
                prerequisiteCandidate = nil
            } else {
                prerequisiteCandidate = fallbackDoorDashModifierCandidate(
                    in: candidates,
                    activeGroup: activeGroupKind,
                    disallowedGroups: protectedGroups
                )
            }
        } else {
            prerequisiteCandidate = fallbackDoorDashModifierCandidate(
                in: candidates,
                activeGroup: activeGroupKind,
                disallowedGroups: protectedGroups
            )
        }

        let focusKind: DoorDashCustomizerFocusKind
        let focusLabel: String
        let filteredCandidates: [WebsiteC2ACandidate]

        if !remainingModifierTerms.isEmpty {
            if let targetCandidate {
                focusKind = .requestedModifier
                focusLabel = "Resolve \(remainingModifierTerms.joined(separator: ", "))"
                let stepCandidates = candidates.filter { ["dd_modifier_option", "dd_modal_close"].contains($0.role) }
                filteredCandidates = stepCandidates.isEmpty ? candidates : stepCandidates
            } else if activeGroupRequired, activeGroupResolved, saveCandidate != nil {
                focusKind = .saveStep
                focusLabel = "Commit resolved \(activeGroupLabel.isEmpty ? "customizer step" : activeGroupLabel)"
                let saveStep = candidates.filter { ["dd_modifier_save", "dd_modal_close"].contains($0.role) }
                filteredCandidates = saveStep.isEmpty ? candidates : saveStep
            } else if activeGroupRequired, prerequisiteCandidate == nil {
                focusKind = .waiting
                focusLabel = activeGroupLabel.isEmpty
                    ? "Waiting for required customizer step"
                    : "Waiting for required \(activeGroupLabel)"
                filteredCandidates = candidates
            } else if shouldSaveAfterModifierSelection(
                saveCandidate: saveCandidate,
                requestedTerms: requestedModifierTerms,
                activeGroup: activeGroupKind,
                activeGroupRequired: activeGroupRequired,
                preservedGroups: preservedGroups
            ) {
                focusKind = .saveStep
                focusLabel = "Save current customizer step"
                let saveStep = candidates.filter { ["dd_modifier_save", "dd_modal_close"].contains($0.role) }
                filteredCandidates = saveStep.isEmpty ? candidates : saveStep
            } else if let prerequisiteCandidate {
                focusKind = .prerequisiteModifier
                focusLabel = "Clear prerequisite: \(prerequisiteCandidate.label)"
                let stepCandidates = candidates.filter { ["dd_modifier_option", "dd_modal_close"].contains($0.role) }
                filteredCandidates = stepCandidates.isEmpty ? candidates : stepCandidates
            } else if saveCandidate != nil {
                focusKind = .saveStep
                focusLabel = "Save current customizer step"
                let saveStep = candidates.filter { ["dd_modifier_save", "dd_modal_close"].contains($0.role) }
                filteredCandidates = saveStep.isEmpty ? candidates : saveStep
            } else {
                focusKind = .waiting
                focusLabel = "Waiting for next customizer step"
                filteredCandidates = candidates
            }
        } else if saveCandidate != nil && addCandidate == nil {
            focusKind = .saveStep
            focusLabel = "Save current customizer step"
            let saveStep = candidates.filter { ["dd_modifier_save", "dd_modal_close"].contains($0.role) }
            filteredCandidates = saveStep.isEmpty ? candidates : saveStep
        } else if addCandidate != nil {
            focusKind = .reviewStep
            focusLabel = "Add to cart"
            let reviewStep = candidates.filter { ["dd_add_to_cart", "dd_cart_cta", "dd_modal_close"].contains($0.role) }
            filteredCandidates = reviewStep.isEmpty ? candidates : reviewStep
        } else {
            focusKind = .waiting
            focusLabel = "Waiting for next customizer step"
            filteredCandidates = candidates
        }

        return DoorDashCustomizerSnapshot(
            focusKind: focusKind,
            activeGroupKind: activeGroupKind,
            activeGroupLabel: activeGroupLabel,
            activeGroupRequired: activeGroupRequired,
            activeGroupResolved: activeGroupResolved,
            stage: modifierTargets.stage,
            remainingTerms: remainingModifierTerms,
            requestedTerms: requestedModifierTerms,
            preservedGroups: preservedGroups,
            traversedDerivedGroups: traversedDerivedGroups,
            focusLabel: focusLabel,
            targetCandidate: targetCandidate,
            prerequisiteCandidate: prerequisiteCandidate,
            saveCandidate: saveCandidate,
            addCandidate: addCandidate,
            filteredCandidates: filteredCandidates,
            addToCartAllowed: remainingModifierTerms.isEmpty && inFlightModifierTerms.isEmpty && !doorDashModifierCommitPending,
            finalReviewBridgeActive: finalReviewBridgeActive
        )
    }

    private struct DoorDashWorkflowPlannerState {
        let remainingTerms: [String]
        let inFlightTerms: [String]
        let commitPending: Bool
        let addToCartAllowed: Bool
        let lastTransitionKind: DoorDashCustomizerFocusKind?
    }

    private struct DoorDashWorkflowTransition {
        let kind: DoorDashCustomizerFocusKind
        let candidate: WebsiteC2ACandidate?
        let consumedTerms: [String]
        let score: Double
        let nextState: DoorDashWorkflowPlannerState
    }

    private struct DoorDashWorkflowPlan {
        let snapshot: DoorDashCustomizerSnapshot
        let plannerState: DoorDashWorkflowPlannerState
        let focusKind: DoorDashCustomizerFocusKind
        let focusLabel: String
        let allowedCandidates: [WebsiteC2ACandidate]
        let nextTransition: DoorDashWorkflowTransition?
    }

    private func makeDoorDashWorkflowPlannerState(
        remainingTerms: [String],
        inFlightTerms: [String],
        commitPending: Bool,
        lastTransitionKind: DoorDashCustomizerFocusKind?
    ) -> DoorDashWorkflowPlannerState {
        let normalizedRemaining = remainingTerms.filter { !$0.isEmpty }
        let normalizedInFlight = inFlightTerms.filter { !$0.isEmpty }
        return DoorDashWorkflowPlannerState(
            remainingTerms: normalizedRemaining,
            inFlightTerms: normalizedInFlight,
            commitPending: commitPending,
            addToCartAllowed: normalizedRemaining.isEmpty && normalizedInFlight.isEmpty && !commitPending,
            lastTransitionKind: lastTransitionKind
        )
    }

    private func currentDoorDashCommitKind() -> DoorDashCustomizerFocusKind? {
        switch doorDashPendingCommitKind {
        case "requested":
            return .requestedModifier
        case "prerequisite":
            return .prerequisiteModifier
        default:
            return nil
        }
    }

    private func initialDoorDashWorkflowPlannerState(from snapshot: DoorDashCustomizerSnapshot) -> DoorDashWorkflowPlannerState {
        makeDoorDashWorkflowPlannerState(
            remainingTerms: snapshot.remainingTerms,
            inFlightTerms: Array(inFlightModifierTerms).sorted(),
            commitPending: doorDashModifierCommitPending,
            lastTransitionKind: currentDoorDashCommitKind()
        )
    }

    private func legalDoorDashWorkflowTransitions(
        for snapshot: DoorDashCustomizerSnapshot,
        plannerState: DoorDashWorkflowPlannerState
    ) -> [DoorDashWorkflowTransition] {
        var transitions: [DoorDashWorkflowTransition] = []
        let activeGroup = snapshot.activeGroupKind
        let preferredGroups = preferredDoorDashGroupKinds(for: snapshot.stage)
        let prerequisiteOverlapsRequested = snapshot.prerequisiteCandidate.map {
            !candidateMatchedModifierTerms($0, targetTerms: plannerState.remainingTerms).isEmpty
        } ?? false

        func requestedTransition(scoreBase: Double) -> DoorDashWorkflowTransition? {
            let requestedCandidate = snapshot.targetCandidate
                ?? (prerequisiteOverlapsRequested ? snapshot.prerequisiteCandidate : nil)
            guard let target = requestedCandidate else {
                return nil
            }
            let targetGroup = doorDashGroupKind(for: target)
            let targetAllowed = activeGroup == .unknown
                || targetGroup == activeGroup
                || preferredGroups.contains(targetGroup)
                || (snapshot.stage == .toppings && activeGroup == .toppingSide)
            guard targetAllowed else {
                return nil
            }
            let matched = candidateMatchedModifierTerms(target, targetTerms: plannerState.remainingTerms)
            guard !matched.isEmpty else {
                return nil
            }
            let nextRemaining = plannerState.remainingTerms.filter { !matched.contains($0) }
            let nextInFlight = Array(Set(plannerState.inFlightTerms).union(matched)).sorted()
            let score = scoreBase
                + Double(matched.count * 10)
                + (targetGroup == .size || targetGroup == .topping ? 6.0 : 0.0)
            return DoorDashWorkflowTransition(
                kind: .requestedModifier,
                candidate: target,
                consumedTerms: matched,
                score: score,
                nextState: makeDoorDashWorkflowPlannerState(
                    remainingTerms: nextRemaining,
                    inFlightTerms: nextInFlight,
                    commitPending: true,
                    lastTransitionKind: .requestedModifier
                )
            )
        }

        if plannerState.commitPending {
            if !snapshot.activeGroupRequired || snapshot.activeGroupResolved {
                if let requested = requestedTransition(scoreBase: 176) {
                    transitions.append(requested)
                }
            }

            if plannerState.lastTransitionKind == .requestedModifier,
               activeGroup == .toppingSide,
               let prerequisite = snapshot.prerequisiteCandidate
            {
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .prerequisiteModifier,
                        candidate: prerequisite,
                        consumedTerms: [],
                        score: 160,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: plannerState.inFlightTerms,
                            commitPending: true,
                            lastTransitionKind: .prerequisiteModifier
                        )
                    )
                )
            }

            if plannerState.lastTransitionKind == .requestedModifier,
               activeGroup == .crust,
               let prerequisite = snapshot.prerequisiteCandidate
            {
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .prerequisiteModifier,
                        candidate: prerequisite,
                        consumedTerms: [],
                        score: 150,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: plannerState.inFlightTerms,
                            commitPending: true,
                            lastTransitionKind: .prerequisiteModifier
                        )
                    )
                )
            }

            if let save = snapshot.saveCandidate,
               (!snapshot.activeGroupRequired || snapshot.activeGroupResolved) {
                let saveScore: Double
                if plannerState.lastTransitionKind == .prerequisiteModifier
                    || activeGroup == .unknown
                    || snapshot.prerequisiteCandidate == nil
                {
                    saveScore = 155
                } else {
                    saveScore = 65
                }
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .saveStep,
                        candidate: save,
                        consumedTerms: [],
                        score: saveScore,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: [],
                            commitPending: false,
                            lastTransitionKind: .saveStep
                        )
                    )
                )
            }

            if transitions.isEmpty, let prerequisite = snapshot.prerequisiteCandidate, activeGroup == .crust || activeGroup == .toppingSide {
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .prerequisiteModifier,
                        candidate: prerequisite,
                        consumedTerms: [],
                        score: 110,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: plannerState.inFlightTerms,
                            commitPending: true,
                            lastTransitionKind: .prerequisiteModifier
                        )
                    )
                )
            }

            if transitions.isEmpty,
               snapshot.activeGroupRequired,
               snapshot.activeGroupResolved,
               let save = snapshot.saveCandidate {
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .saveStep,
                        candidate: save,
                        consumedTerms: [],
                        score: 145,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: [],
                            commitPending: false,
                            lastTransitionKind: .saveStep
                        )
                    )
                )
            }
        } else {
            if let requested = requestedTransition(scoreBase: 176) {
                transitions.append(requested)
            } else if snapshot.activeGroupRequired,
                      snapshot.activeGroupResolved,
                      let save = snapshot.saveCandidate {
                transitions.append(
                    DoorDashWorkflowTransition(
                        kind: .saveStep,
                        candidate: save,
                        consumedTerms: [],
                        score: 140,
                        nextState: makeDoorDashWorkflowPlannerState(
                            remainingTerms: plannerState.remainingTerms,
                            inFlightTerms: plannerState.inFlightTerms,
                            commitPending: false,
                            lastTransitionKind: .saveStep
                        )
                    )
                )
            }

            if plannerState.remainingTerms.isEmpty && plannerState.inFlightTerms.isEmpty {
                if let add = snapshot.addCandidate,
                   activeGroup == .review || activeGroup == .unknown || snapshot.finalReviewBridgeActive {
                    transitions.append(
                        DoorDashWorkflowTransition(
                            kind: .reviewStep,
                            candidate: add,
                            consumedTerms: [],
                            score: 190,
                            nextState: makeDoorDashWorkflowPlannerState(
                                remainingTerms: [],
                                inFlightTerms: [],
                                commitPending: false,
                                lastTransitionKind: .reviewStep
                            )
                        )
                    )
                } else if let save = snapshot.saveCandidate, activeGroup != .review {
                    transitions.append(
                        DoorDashWorkflowTransition(
                            kind: .saveStep,
                            candidate: save,
                            consumedTerms: [],
                            score: 90,
                            nextState: makeDoorDashWorkflowPlannerState(
                                remainingTerms: [],
                                inFlightTerms: [],
                                commitPending: false,
                                lastTransitionKind: .saveStep
                            )
                        )
                    )
                }
            } else if let prerequisite = snapshot.prerequisiteCandidate, !prerequisiteOverlapsRequested {
                let prerequisiteGroup = doorDashGroupKind(for: prerequisite)
                let canUsePrerequisite = snapshot.targetCandidate == nil
                    || activeGroup == .crust
                    || activeGroup == .toppingSide
                    || activeGroup == .unknown
                    || prerequisiteGroup == activeGroup
                if canUsePrerequisite {
                    transitions.append(
                        DoorDashWorkflowTransition(
                            kind: .prerequisiteModifier,
                            candidate: prerequisite,
                            consumedTerms: [],
                            score: 85,
                            nextState: makeDoorDashWorkflowPlannerState(
                                remainingTerms: plannerState.remainingTerms,
                                inFlightTerms: plannerState.inFlightTerms,
                                commitPending: true,
                                lastTransitionKind: .prerequisiteModifier
                            )
                        )
                    )
                }
            }
        }

        if transitions.isEmpty {
            transitions.append(
                DoorDashWorkflowTransition(
                    kind: .waiting,
                    candidate: nil,
                    consumedTerms: [],
                    score: -40,
                    nextState: plannerState
                )
            )
        }

        return transitions.sorted { left, right in
            if left.score == right.score {
                return readableDoorDashFocusKind(left.kind) < readableDoorDashFocusKind(right.kind)
            }
            return left.score > right.score
        }
    }

    private func baseDoorDashWorkflowScore(for plannerState: DoorDashWorkflowPlannerState) -> Double {
        var score = 0.0
        score -= Double(plannerState.remainingTerms.count) * 32.0
        score -= Double(plannerState.inFlightTerms.count) * 14.0
        if plannerState.commitPending {
            score -= 18.0
        }
        if plannerState.addToCartAllowed {
            score += 90.0
        }
        return score
    }

    private func scoreDoorDashWorkflowPath(
        from snapshot: DoorDashCustomizerSnapshot,
        plannerState: DoorDashWorkflowPlannerState,
        depth: Int
    ) -> (score: Double, firstTransition: DoorDashWorkflowTransition?) {
        let transitions = legalDoorDashWorkflowTransitions(for: snapshot, plannerState: plannerState)
        guard depth > 0 else {
            return (baseDoorDashWorkflowScore(for: plannerState), nil)
        }

        var bestScore = -Double.infinity
        var bestFirst: DoorDashWorkflowTransition?

        for transition in transitions {
            let future = depth > 1
                ? scoreDoorDashWorkflowPath(from: snapshot, plannerState: transition.nextState, depth: depth - 1)
                : (score: baseDoorDashWorkflowScore(for: transition.nextState), firstTransition: nil as DoorDashWorkflowTransition?)
            let total = transition.score + (future.score * 0.72) + baseDoorDashWorkflowScore(for: transition.nextState)
            if total > bestScore {
                bestScore = total
                bestFirst = transition.kind == .waiting ? nil : transition
            }
        }

        return (bestScore, bestFirst)
    }

    private func allowedDoorDashWorkflowCandidates(
        for focusKind: DoorDashCustomizerFocusKind,
        snapshot: DoorDashCustomizerSnapshot,
        candidates: [WebsiteC2ACandidate]
    ) -> [WebsiteC2ACandidate] {
        let candidatePool = snapshot.addCandidate.map { add in
            candidates.contains(where: { $0.id == add.id }) ? candidates : (candidates + [add])
        } ?? candidates

        let filtered: [WebsiteC2ACandidate]
        switch focusKind {
        case .requestedModifier, .prerequisiteModifier:
            filtered = candidatePool.filter { candidate in
                guard ["dd_modifier_option", "dd_modal_close"].contains(candidate.role) else {
                    return false
                }
                if candidate.role != "dd_modifier_option" {
                    return true
                }
                let candidateGroup = doorDashGroupKind(for: candidate)
                let protectedGroups = snapshot.preservedGroups.union(snapshot.traversedDerivedGroups)
                if protectedGroups.contains(candidateGroup), candidateGroup != snapshot.activeGroupKind {
                    return false
                }
                let preferredGroups = preferredDoorDashGroupKinds(for: snapshot.stage)
                return snapshot.activeGroupKind == .unknown
                    || candidateGroup == snapshot.activeGroupKind
                    || preferredGroups.contains(candidateGroup)
            }
        case .saveStep:
            filtered = candidatePool.filter { ["dd_modifier_save", "dd_modal_close"].contains($0.role) }
        case .reviewStep:
            filtered = candidatePool.filter { ["dd_add_to_cart", "dd_cart_cta", "dd_modal_close"].contains($0.role) }
        case .waiting:
            filtered = snapshot.filteredCandidates
        }
        return filtered.isEmpty ? snapshot.filteredCandidates : filtered
    }

    private func focusLabelForDoorDashWorkflowPlan(
        focusKind: DoorDashCustomizerFocusKind,
        snapshot: DoorDashCustomizerSnapshot,
        plannerState: DoorDashWorkflowPlannerState
    ) -> String {
        switch focusKind {
        case .requestedModifier:
            if !plannerState.remainingTerms.isEmpty {
                if !snapshot.activeGroupLabel.isEmpty {
                    return "\(snapshot.activeGroupLabel): \(plannerState.remainingTerms.joined(separator: ", "))"
                }
                return "Resolve \(plannerState.remainingTerms.joined(separator: ", "))"
            }
            return "Resolve requested modifier"
        case .prerequisiteModifier:
            if let prerequisite = snapshot.prerequisiteCandidate {
                return "Complete prerequisite: \(prerequisite.label)"
            }
            return "Complete prerequisite customizer step"
        case .saveStep:
            return "Commit current customizer step"
        case .reviewStep:
            return "Add to cart"
        case .waiting:
            return "Waiting for next customizer transition"
        }
    }

    private func planDoorDashCustomizerWorkflow(
        from candidates: [WebsiteC2ACandidate],
        state: WebsiteC2AState
    ) -> DoorDashWorkflowPlan {
        let snapshot = doorDashCustomizerSnapshot(from: candidates, state: state)
        let plannerState = initialDoorDashWorkflowPlannerState(from: snapshot)
        let search = scoreDoorDashWorkflowPath(from: snapshot, plannerState: plannerState, depth: 4)
        let nextTransition = search.firstTransition
        let focusKind = nextTransition?.kind ?? snapshot.focusKind
        let allowedCandidates = allowedDoorDashWorkflowCandidates(for: focusKind, snapshot: snapshot, candidates: candidates)
        let focusLabel = focusLabelForDoorDashWorkflowPlan(
            focusKind: focusKind,
            snapshot: snapshot,
            plannerState: plannerState
        )
        return DoorDashWorkflowPlan(
            snapshot: snapshot,
            plannerState: plannerState,
            focusKind: focusKind,
            focusLabel: focusLabel,
            allowedCandidates: allowedCandidates,
            nextTransition: nextTransition
        )
    }

    private func focusedDoorDashItemModalCandidates(from candidates: [WebsiteC2ACandidate], state: WebsiteC2AState) -> [WebsiteC2ACandidate] {
        return planDoorDashCustomizerWorkflow(from: candidates, state: state).allowedCandidates
    }

    private func readableDoorDashFocusKind(_ kind: DoorDashCustomizerFocusKind) -> String {
        switch kind {
        case .requestedModifier:
            return "requested modifier"
        case .prerequisiteModifier:
            return "prerequisite modifier"
        case .saveStep:
            return "save step"
        case .reviewStep:
            return "review step"
        case .waiting:
            return "waiting"
        }
    }

    private func readableDoorDashGroupKind(_ kind: DoorDashCustomizerGroupKind) -> String {
        switch kind {
        case .size:
            return "size"
        case .crust:
            return "crust"
        case .topping:
            return "topping"
        case .toppingSide:
            return "topping side"
        case .preferences:
            return "preferences"
        case .review:
            return "review"
        case .unknown:
            return "unknown"
        }
    }

    private func maybeTraceDoorDashWorkflowPlan(_ plan: DoorDashWorkflowPlan) {
        let nextRole = plan.nextTransition?.candidate?.role ?? "none"
        let nextLabel = normalizedCommerceTerm(plan.nextTransition?.candidate?.label ?? readableDoorDashFocusKind(plan.focusKind))
        let marker = [
            readableDoorDashGroupKind(plan.snapshot.activeGroupKind),
            normalizedCommerceTerm(plan.snapshot.activeGroupLabel),
            plan.snapshot.activeGroupRequired ? "required" : "optional",
            readableDoorDashFocusKind(plan.focusKind),
            nextRole,
            nextLabel,
            plan.plannerState.remainingTerms.joined(separator: ","),
            plan.plannerState.inFlightTerms.joined(separator: ","),
            plan.snapshot.traversedDerivedGroups.map(\.rawValue).sorted().joined(separator: ","),
            plan.plannerState.commitPending ? "commit_pending" : "commit_clear"
        ].joined(separator: "|")
        guard marker != lastDoorDashPlannerMarker else {
            return
        }
        lastDoorDashPlannerMarker = marker

        var parts = [
            "Planner: group=\(readableDoorDashGroupKind(plan.snapshot.activeGroupKind))",
            "focus=\(readableDoorDashFocusKind(plan.focusKind))",
            plan.plannerState.commitPending ? "commit=pending" : "commit=clear"
        ]
        if plan.snapshot.activeGroupRequired {
            parts.append("groupRequired=true")
        }
        if !plan.snapshot.activeGroupLabel.isEmpty {
            parts.append("label=\(plan.snapshot.activeGroupLabel)")
        }
        if !plan.snapshot.preservedGroups.isEmpty {
            let preserved = plan.snapshot.preservedGroups
                .map(readableDoorDashGroupKind)
                .sorted()
                .joined(separator: ", ")
            parts.append("preserve=\(preserved)")
        }
        if !plan.snapshot.traversedDerivedGroups.isEmpty {
            let traversed = plan.snapshot.traversedDerivedGroups
                .map(readableDoorDashGroupKind)
                .sorted()
                .joined(separator: ", ")
            parts.append("derived=\(traversed)")
        }
        if let nextCandidate = plan.nextTransition?.candidate {
            parts.append("next=\(nextCandidate.role):\(nextCandidate.label)")
        } else {
            parts.append("next=none")
        }
        if !plan.plannerState.remainingTerms.isEmpty {
            parts.append("remaining=\(plan.plannerState.remainingTerms.joined(separator: ", "))")
        }
        if !plan.plannerState.inFlightTerms.isEmpty {
            parts.append("inFlight=\(plan.plannerState.inFlightTerms.joined(separator: ", "))")
        }
        appendAgencyTrace(parts.joined(separator: " • "))
    }

    private func mirrorFacts(for state: WebsiteC2AState) -> [WebsiteMirrorFact] {
        var facts: [WebsiteMirrorFact] = [
            WebsiteMirrorFact(id: "page", title: "Page", value: readableRequirement(state.pageKind)),
            WebsiteMirrorFact(id: "auth", title: "Auth", value: readableRequirement(state.authState)),
            WebsiteMirrorFact(id: "actions", title: "Moves", value: "\(state.safeActions.count)")
        ]
        if state.pageKind == "dd_item_modal" {
            let plan = planDoorDashCustomizerWorkflow(from: state.candidates, state: state)
            facts.append(WebsiteMirrorFact(id: "focus", title: "Focus", value: plan.focusLabel))
            facts.append(WebsiteMirrorFact(id: "step", title: "Step", value: readableDoorDashFocusKind(plan.focusKind)))
            facts.append(WebsiteMirrorFact(id: "group", title: "Group", value: readableDoorDashGroupKind(plan.snapshot.activeGroupKind)))
            if !plan.snapshot.activeGroupLabel.isEmpty {
                facts.append(WebsiteMirrorFact(id: "group_label", title: "Group Label", value: plan.snapshot.activeGroupLabel))
            }
            if !plan.plannerState.remainingTerms.isEmpty {
                facts.append(WebsiteMirrorFact(id: "remaining", title: "Remaining", value: plan.plannerState.remainingTerms.joined(separator: ", ")))
            }
            if !plan.plannerState.inFlightTerms.isEmpty {
                facts.append(WebsiteMirrorFact(id: "inflight", title: "In Flight", value: plan.plannerState.inFlightTerms.joined(separator: ", ")))
            }
        }
        if let verification = state.capsuleVerification {
            facts.append(WebsiteMirrorFact(id: "matched", title: "Matched", value: "\(verification.matched.count)"))
            if !verification.missing.isEmpty {
                facts.append(WebsiteMirrorFact(id: "missing", title: "Missing", value: "\(verification.missing.count)"))
            }
        }
        if let best = mirrorCandidates(for: state).first {
            facts.append(WebsiteMirrorFact(id: "best", title: "Best", value: best.label))
        }
        return facts
    }

    private func mirrorTitle(for state: WebsiteC2AState) -> String {
        switch state.pageKind {
        case "ub_trip_builder":
            return "Uber trip builder distilled"
        case "ub_product_selection":
            return "Uber ride options are ready"
        case "ue_entry_gate":
            return "Uber Eats entry gate"
        case "ue_search_results":
            return "Uber Eats search results distilled"
        case "ue_storefront":
            return "Uber Eats storefront distilled"
        case "ue_item_modal":
            return "Uber Eats customizer is active"
        case "ue_cart_page":
            return "Uber Eats cart is ready"
        case "ue_checkout":
            return "Uber Eats checkout detected"
        case "dd_search_results":
            return "DoorDash search results distilled"
        case "dd_storefront":
            return "DoorDash storefront distilled"
        case "dd_item_modal":
            return "DoorDash customizer is active"
        case "dd_cart_drawer":
            return "DoorDash cart drawer is active"
        case "dd_cart_page":
            return "DoorDash cart is ready"
        case "dd_checkout":
            return "DoorDash checkout detected"
        case "dd_payment_sheet":
            return "Payment sheet is active"
        case "login":
            return "Session needs recovery"
        case "search_results", "search_form":
            return "Mirror has a search surface"
        case "menu_or_item":
            return "Mirror distilled the item funnel"
        case "cart":
            return "Mirror sees a cart checkpoint"
        case "checkout":
            return "Mirror reached final review"
        default:
            return "Mirror distilled the current page"
        }
    }

    private func mirrorSummary(for state: WebsiteC2AState, step: WebsiteGuidedStep) -> String {
        if let best = mirrorCandidates(for: state).first {
            return "\(step.detail) Best distilled candidate: \(best.label)."
        }
        return step.detail
    }

    private func mirrorIcon(for state: WebsiteC2AState) -> String {
        switch state.pageKind {
        case "ub_trip_builder":
            return "car.circle"
        case "ub_product_selection":
            return "car.side"
        case "ue_entry_gate":
            return "rectangle.and.text.magnifyingglass"
        case "ue_search_results":
            return "building.2"
        case "ue_storefront":
            return "storefront"
        case "ue_item_modal":
            return "square.and.pencil"
        case "ue_cart_page":
            return "cart"
        case "ue_checkout":
            return "hand.raised.fill"
        case "dd_search_results":
            return "building.2"
        case "dd_storefront":
            return "storefront"
        case "dd_item_modal":
            return "square.and.pencil"
        case "dd_cart_drawer", "dd_cart_page":
            return "cart"
        case "dd_checkout", "dd_payment_sheet":
            return "hand.raised.fill"
        case "login":
            return "person.badge.key"
        case "menu_or_item":
            return "square.grid.2x2"
        case "cart":
            return "cart"
        case "checkout":
            return "hand.raised.fill"
        default:
            return "sparkles.rectangle.stack"
        }
    }

    private func mirrorColor(for state: WebsiteC2AState) -> Color {
        switch state.pageKind {
        case "ub_trip_builder":
            return .green
        case "ub_product_selection":
            return .orange
        case "ue_entry_gate", "ue_search_results", "ue_storefront", "ue_item_modal", "ue_cart_page":
            return .green
        case "ue_checkout":
            return .red
        case "dd_search_results", "dd_storefront", "dd_item_modal", "dd_cart_drawer", "dd_cart_page":
            return .green
        case "dd_checkout", "dd_payment_sheet":
            return .red
        case "login":
            return .orange
        case "checkout":
            return .red
        case "menu_or_item", "cart":
            return .green
        default:
            return .blue
        }
    }

    private func mirrorCandidateCard(_ candidate: WebsiteC2ACandidate) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(readableRequirement(candidate.role))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(String(format: "%.1f", candidate.score))
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(candidate.score > 0 ? .green : .secondary)
            }
            Text(candidate.label)
                .font(.caption.weight(.semibold))
                .lineLimit(2)
            if !candidate.matchedTerms.isEmpty {
                Text("Matched: \(candidate.matchedTerms.joined(separator: ", "))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text(candidate.reason)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            candidateActionButton(candidate)
        }
        .frame(width: 205, alignment: .leading)
        .padding(8)
        .background(candidate.score > 0 ? Color.green.opacity(0.10) : Color(.tertiarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func mirrorCandidateScroller(_ candidates: [WebsiteC2ACandidate]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 8) {
                ForEach(Array(candidates.prefix(12))) { candidate in
                    mirrorCandidateCard(candidate)
                }
            }
        }
    }

    private func mirrorItemCandidates(for state: WebsiteC2AState) -> [WebsiteC2ACandidate] {
        let itemRoles = Set(["store_link", "menu_item", "dd_store_card", "dd_item_card", "dd_modifier_option", "dd_modifier_save", "ue_store_card", "ue_item_card", "ub_vehicle_option"])
        let filtered = mirrorSectionCandidates(for: state, allowedRoles: itemRoles)
        return filtered.isEmpty ? mirrorSectionCandidates(for: state) : filtered
    }

    private func mirrorControlCandidates(for state: WebsiteC2AState) -> [WebsiteC2ACandidate] {
        let controlRoles = Set(["item_action_button", "cart_button", "cart_link", "control_button", "checkout_button", "dd_add_to_cart", "dd_modifier_save", "dd_continue_cta", "dd_cart_cta", "dd_tip_option", "dd_address_cta", "dd_modal_close", "ue_continue_browser", "ue_address_cta", "ue_address_result", "ue_search_entry", "ue_add_to_cart", "ue_cart_cta", "ue_continue_cta", "ue_modal_close", "ub_pickup_input", "ub_pickup_current_location", "ub_pickup_result", "ub_dropoff_input", "ub_dropoff_result", "ub_see_prices_cta"])
        return mirrorSectionCandidates(for: state, allowedRoles: controlRoles)
    }

    private func mirrorSectionCandidates(for state: WebsiteC2AState, allowedRoles: Set<String>? = nil) -> [WebsiteC2ACandidate] {
        let deprioritizedRoles = Set(["review_link", "accessibility_link", "utility_link", "auth_link", "nav_link", "dd_menu_nav"])
        let visibleCandidates = state.candidates.filter { !deprioritizedRoles.contains($0.role) && !$0.blocked }
        let filtered: [WebsiteC2ACandidate]
        if let allowedRoles {
            filtered = visibleCandidates.filter { allowedRoles.contains($0.role) }
        } else {
            filtered = visibleCandidates
        }
        let sorted = filtered.sorted { left, right in
            let leftPriority = mirrorRolePriority(pageKind: state.pageKind, role: left.role)
            let rightPriority = mirrorRolePriority(pageKind: state.pageKind, role: right.role)
            if leftPriority != rightPriority {
                return leftPriority > rightPriority
            }
            if left.score != right.score {
                return left.score > right.score
            }
            return left.label.localizedCaseInsensitiveCompare(right.label) == .orderedAscending
        }
        return Array(sorted.prefix(12))
    }

    private func mirrorItemSectionTitle(for state: WebsiteC2AState) -> String {
        switch state.pageKind {
        case "ub_trip_builder":
            return "Trip Controls"
        case "ub_product_selection":
            return "Ride Options"
        case "ue_entry_gate":
            return "Setup Gates"
        case "ue_search_results":
            return "Store Cards"
        case "ue_storefront":
            return "Menu Items"
        case "ue_item_modal":
            return "Customizer Items"
        case "ue_cart_page":
            return "Cart Signals"
        case "ue_checkout":
            return "Checkout Signals"
        case "dd_search_results":
            return "Store Cards"
        case "dd_storefront":
            return "Menu Items"
        case "dd_item_modal":
            return "Customizer Steps"
        case "dd_cart_drawer":
            return "Cart Signals"
        case "dd_checkout":
            return "Checkout Signals"
        case "search_results", "search_form":
            return "Relevant Results"
        case "menu_or_item":
            return "Relevant Items"
        case "cart":
            return "Cart Links"
        case "checkout":
            return "Checkout Signals"
        default:
            return "Relevant Candidates"
        }
    }

    private func mirrorSectionCard<Content: View>(title: String, systemImage: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.semibold))
            content()
        }
        .padding(12)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    private func guidedStepControls(for state: WebsiteC2AState) -> some View {
        let step = guidedStep(for: state)
        return HStack(alignment: .top, spacing: 8) {
            Image(systemName: step.icon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(guidanceColor(step.tone))
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 3) {
                Text(step.title)
                    .font(.caption.weight(.semibold))
                Text(step.detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .background(guidanceColor(step.tone).opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    @ViewBuilder
    private func authBridgeControls(for state: WebsiteC2AState) -> some View {
        if state.authState == "login_required" || state.authState == "likely_signed_in" {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Label("Auth Bridge", systemImage: "person.badge.key")
                        .font(.caption.weight(.semibold))
                    Spacer()
                    Text(state.authDomain.isEmpty ? "current site" : state.authDomain)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Text(authGuidance(for: state))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                HStack(spacing: 8) {
                    Button("I Signed In, Inspect Again") {
                        isC2AConsoleClosed = false
                        browser.inspectPage(capsule: route.capsule)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(browser.isInspecting || browser.isLoading)

                    Button("Mark Session Likely") {
                        rememberSessionLikely(for: state)
                    }
                    .buttonStyle(.bordered)
                    .disabled(state.authDomain.isEmpty)
                }
                if let note = rememberedAuthNote(for: state), !note.isEmpty {
                    Text(note)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            .padding(8)
            .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }

    @ViewBuilder
    private func capsuleVerificationControls(for state: WebsiteC2AState) -> some View {
        if let verification = state.capsuleVerification {
            let isFinalReview = state.pageKind == "checkout" || state.pageKind == "ue_checkout"
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Label("Capsule Match", systemImage: isFinalReview ? "hand.raised.fill" : "checklist")
                        .font(.caption.weight(.semibold))
                    Spacer()
                    Text(readableRequirement(state.pageKind))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Text(verification.summary)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                if !verification.matched.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(verification.matched, id: \.self) { item in
                                Label(readableRequirement(item), systemImage: "checkmark.circle.fill")
                                    .font(.caption2)
                                    .foregroundStyle(.green)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 5)
                                    .background(Color.green.opacity(0.12), in: Capsule())
                            }
                        }
                    }
                }
                if !verification.missing.isEmpty {
                    Text("Missing: \(verification.missing.map { readableRequirement($0) }.joined(separator: ", "))")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                        .lineLimit(2)
                }
                if !verification.warnings.isEmpty {
                    Text("Policy: \(verification.warnings.map { readableRequirement($0) }.joined(separator: ", "))")
                        .font(.caption2)
                        .foregroundStyle(isFinalReview ? .red : .secondary)
                        .lineLimit(2)
                }
            }
            .padding(8)
            .background((isFinalReview ? Color.red : Color.blue).opacity(0.10), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }

    @ViewBuilder
    private func candidateControls(for state: WebsiteC2AState) -> some View {
        if !state.candidates.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Ranked Candidates")
                    .font(.caption.weight(.semibold))
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 8) {
                        ForEach(Array(state.candidates.prefix(8))) { candidate in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(readableRequirement(candidate.role))
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                    Spacer()
                                    Text(String(format: "%.1f", candidate.score))
                                        .font(.caption2.weight(.semibold))
                                        .foregroundStyle(candidate.score > 0 ? .green : .secondary)
                                }
                                Text(candidate.label)
                                    .font(.caption.weight(.semibold))
                                    .lineLimit(2)
                                Text(candidate.reason)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                if candidate.kind == "button" && candidate.url.isEmpty {
                                    Text(candidate.tapReason)
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }
                                candidateActionButton(candidate)
                            }
                            .frame(width: 190, alignment: .leading)
                            .padding(8)
                            .background(candidate.score > 0 ? Color.green.opacity(0.10) : Color(.tertiarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                    }
                }
                if !browser.buttonActionStatus.isEmpty {
                    Text(browser.buttonActionStatus)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
    }

    @ViewBuilder
    private func candidateActionButton(_ candidate: WebsiteC2ACandidate) -> some View {
        if candidate.blocked {
            Button("Blocked") {
            }
            .buttonStyle(.bordered)
            .disabled(true)
        } else if !candidate.url.isEmpty {
            Button(candidateOpenTitle(candidate)) {
                openCandidate(candidate)
            }
            .buttonStyle(.bordered)
        } else if candidate.kind == "button" && candidate.tapSafety == "safe" {
            Button(browser.isRunningButtonAction ? "Tapping..." : candidateTapTitle(candidate, allowCaution: false)) {
                tapCandidate(candidate)
            }
            .buttonStyle(.borderedProminent)
            .disabled(browser.isRunningButtonAction)
        } else if candidate.kind == "button" && candidate.tapSafety == "caution" {
            Button(browser.isRunningButtonAction ? "Tapping..." : candidateTapTitle(candidate, allowCaution: true)) {
                tapCandidate(candidate, allowCaution: true)
            }
            .buttonStyle(.bordered)
            .tint(.orange)
            .disabled(browser.isRunningButtonAction)
        } else {
            Button("No Action") {
            }
            .buttonStyle(.bordered)
            .disabled(true)
        }
    }

    private func candidateOpenTitle(_ candidate: WebsiteC2ACandidate) -> String {
        switch candidate.role {
        case "ub_see_prices_cta":
            return "See Prices"
        case "dd_store_card":
            return "Open Store"
        case "dd_item_card":
            return "Open Item"
        case "ue_store_card":
            return "Open Store"
        case "ue_item_card":
            return "Open Item"
        case "dd_continue_cta":
            return "Continue"
        case "ue_continue_cta":
            return "Next"
        case "cart_link", "dd_cart_cta":
            return "Open Cart"
        case "ue_cart_cta":
            return "Open Cart"
        default:
            return "Open"
        }
    }

    private func candidateTapTitle(_ candidate: WebsiteC2ACandidate, allowCaution: Bool) -> String {
        switch candidate.role {
        case "ub_pickup_input":
            return "Set Pickup"
        case "ub_pickup_current_location":
            return "Use Current Location"
        case "ub_pickup_result":
            return "Use Current Location"
        case "ub_dropoff_input":
            return "Set Destination"
        case "ub_dropoff_result":
            return "Choose Destination"
        case "ub_see_prices_cta":
            return "See Prices"
        case "dd_cart_cta":
            return "Open Cart"
        case "dd_continue_cta":
            return "Continue"
        case "dd_add_to_cart":
            return "Add To Cart"
        case "dd_modifier_option":
            return "Select Option"
        case "dd_modifier_save":
            return candidate.label.localizedCaseInsensitiveContains("save") ? "Save" : "Save Options"
        case "ue_continue_browser":
            return "Continue In Browser"
        case "ue_address_cta":
            return "Open Address"
        case "ue_address_result":
            return "Select Address"
        case "ue_search_entry":
            return "Open Search"
        case "ue_cart_cta":
            return "Open Cart"
        case "ue_continue_cta":
            return "Next"
        case "ue_add_to_cart":
            return "Add To Order"
        case "ue_modal_close":
            return "Dismiss"
        case "dd_tip_option":
            return "Set Tip"
        case "dd_modal_close":
            return "Dismiss"
        case "checkout_button":
            return "Enter Checkout"
        default:
            if allowCaution {
                return candidate.label.localizedCaseInsensitiveContains("checkout") ? "Enter Checkout" : "Tap Reviewed"
            }
            return "Tap"
        }
    }

    @ViewBuilder
    private func searchActionControls(for state: WebsiteC2AState) -> some View {
        if let query = searchQueryIfAvailable(for: state) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Safe Search Primitive")
                    .font(.caption.weight(.semibold))
                HStack(spacing: 8) {
                    Button("Fill Search") {
                        browser.fillSearchQuery(query, submit: false, capsule: route.capsule)
                    }
                    .buttonStyle(.bordered)
                    .disabled(browser.isRunningSearchAction)

                    Button("Fill + Submit") {
                        browser.fillSearchQuery(query, submit: true, capsule: route.capsule)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(browser.isRunningSearchAction)
                }
                Text("Query: \(query)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if !browser.searchActionStatus.isEmpty {
                    Text(browser.searchActionStatus)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
    }

    @ViewBuilder
    private func bridgeSuggestionControls(for state: WebsiteC2AState) -> some View {
        if !bridgeSuggestions(for: state).isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Bridge Suggestions")
                    .font(.caption.weight(.semibold))
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(bridgeSuggestions(for: state)) { suggestion in
                            Button(suggestion.option.label) {
                                openBridgeOption(suggestion.option)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
                Text(bridgeSuggestions(for: state).map { $0.reason }.joined(separator: " "))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func verificationChecklist(for capsule: ActionCapsule) -> some View {
        let requirements = capsule.verifierRequirements.isEmpty ? commerceChecklist : capsule.verifierRequirements
        VStack(alignment: .leading, spacing: 6) {
            Text("Verify Before Final Action")
                .font(.caption.weight(.semibold))
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(requirements.prefix(7), id: \.self) { item in
                        Button {
                            toggleVerified(item)
                        } label: {
                            Label(readableRequirement(item), systemImage: verifiedItems.contains(item) ? "checkmark.circle.fill" : "circle")
                                .font(.caption2)
                        }
                        .buttonStyle(.bordered)
                        .tint(verifiedItems.contains(item) ? .green : .gray)
                    }
                }
            }
            if !capsule.autoSubmitBlockers.isEmpty {
                Text("Auto-submit blocked: \(capsule.autoSubmitBlockers.prefix(3).joined(separator: ", "))")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
    }

    private func capsuleChip(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color(.tertiarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func toggleVerified(_ item: String) {
        if verifiedItems.contains(item) {
            verifiedItems.remove(item)
        } else {
            verifiedItems.insert(item)
        }
    }

    private func authGuidance(for state: WebsiteC2AState) -> String {
        if state.authState == "login_required" {
            return "Sign in manually inside this browser if you trust the site, then tap inspect again. Memla does not store passwords or bypass 2FA/captcha."
        }
        if state.authState == "likely_signed_in" {
            return "This page has account/cart/address hints, so the session may be active. Continue with capsule verification before final checkout."
        }
        return "Session status is unknown. Inspect after any manual sign-in to refresh Website C2A."
    }

    private func authMemoryKey(for state: WebsiteC2AState) -> String {
        "memla.auth.\(state.authDomain)"
    }

    private func rememberSessionLikely(for state: WebsiteC2AState) {
        guard !state.authDomain.isEmpty else {
            return
        }
        let note = "Session marked likely for \(state.authDomain). Memla stores no credentials."
        UserDefaults.standard.set(note, forKey: authMemoryKey(for: state))
        authNotes[state.authDomain] = note
    }

    private func rememberedAuthNote(for state: WebsiteC2AState) -> String? {
        guard !state.authDomain.isEmpty else {
            return nil
        }
        if let note = authNotes[state.authDomain] {
            return note
        }
        return UserDefaults.standard.string(forKey: authMemoryKey(for: state))
    }

    private func guidedStep(for state: WebsiteC2AState) -> WebsiteGuidedStep {
        if state.pageKind == "ub_product_selection" {
            return WebsiteGuidedStep(
                title: "Review the ride quote",
                detail: "Uber ride options are visible. Compare the vehicle choice and price, then stop before the final Request Uber button.",
                icon: "car.side",
                tone: "warning"
            )
        }
        if state.pageKind == "ub_trip_builder" {
            return WebsiteGuidedStep(
                title: "Set pickup and destination",
                detail: "Uber needs pickup and dropoff first. Prefer current location for pickup, select the destination result, then use See prices.",
                icon: "mappin.and.ellipse",
                tone: "safe"
            )
        }
        if state.pageKind == "ue_checkout" {
            return WebsiteGuidedStep(
                title: "Review checkout details",
                detail: "Uber Eats checkout is visible. Verify address, payment, fees, and total here, then leave payment and final submission to the user.",
                icon: "checklist",
                tone: "warning"
            )
        }
        if state.pageKind == "ue_cart_page" {
            return WebsiteGuidedStep(
                title: "Move from cart to checkout",
                detail: "Uber Eats cart state is active. Focus on View order and Next, then stop once checkout is reached.",
                icon: "cart.badge.questionmark",
                tone: "warning"
            )
        }
        if state.pageKind == "ue_item_modal" {
            return WebsiteGuidedStep(
                title: "Use the customizer layer",
                detail: "The active Uber Eats item customizer is open. Focus on size, quantity, modifiers, and Add to order, not the background storefront.",
                icon: "slider.horizontal.3",
                tone: "safe"
            )
        }
        if state.pageKind == "ue_storefront" {
            return WebsiteGuidedStep(
                title: "Pick a menu item",
                detail: "Uber Eats storefront detected. Prefer actual food items like Build Your Own Pizza over utility links or store info.",
                icon: "fork.knife",
                tone: "safe"
            )
        }
        if state.pageKind == "ue_search_results" {
            return WebsiteGuidedStep(
                title: "Pick the right store card",
                detail: "Uber Eats search results are visible. Prefer merchant cards that match the requested restaurant and ignore generic filters or favorites.",
                icon: "building.2",
                tone: "safe"
            )
        }
        if state.pageKind == "ue_entry_gate" {
            return WebsiteGuidedStep(
                title: "Clear the entry gate",
                detail: "Uber Eats is still at browser/address setup. Continue in browser or complete the delivery address step before Memla can drive the food flow.",
                icon: "rectangle.and.text.magnifyingglass",
                tone: "warning"
            )
        }
        if state.pageKind == "dd_payment_sheet" {
            return WebsiteGuidedStep(
                title: "Stop at payment sheet",
                detail: "DoorDash opened payment selection. This is a hard human boundary, so Memla should not pick a payment method or continue.",
                icon: "hand.raised.fill",
                tone: "danger"
            )
        }
        if state.pageKind == "dd_checkout" {
            return WebsiteGuidedStep(
                title: "Review checkout details",
                detail: "Address, tip, order summary, and total are visible. Verify them here, then leave payment and final order submission to the user.",
                icon: "checklist",
                tone: "warning"
            )
        }
        if state.pageKind == "dd_cart_drawer" || state.pageKind == "dd_cart_page" {
            return WebsiteGuidedStep(
                title: "Move from cart to checkout",
                detail: "DoorDash cart state is active. Suppress store browsing and focus on cart, continue, tip, and address controls.",
                icon: "cart.badge.questionmark",
                tone: "warning"
            )
        }
        if state.pageKind == "dd_item_modal" {
            return WebsiteGuidedStep(
                title: "Use the customizer layer",
                detail: "The active DoorDash item modal is open. Focus on size, quantity, modifiers, and Add to cart, not the background storefront.",
                icon: "slider.horizontal.3",
                tone: "safe"
            )
        }
        if state.pageKind == "dd_storefront" {
            return WebsiteGuidedStep(
                title: "Pick a menu item",
                detail: "DoorDash storefront detected. Prefer food item cards and suppress category or marketing links.",
                icon: "fork.knife",
                tone: "safe"
            )
        }
        if state.pageKind == "dd_search_results" {
            return WebsiteGuidedStep(
                title: "Pick the right store card",
                detail: "DoorDash search results are visible. Prefer merchant cards that match the requested restaurant, rating, and distance.",
                icon: "building.2",
                tone: "safe"
            )
        }
        if state.pageKind == "checkout" || state.residuals.contains("irreversible_action_nearby") {
            return WebsiteGuidedStep(
                title: "Stop before final action",
                detail: "Checkout or payment language is visible. Verify the capsule checklist and let the user make the final purchase decision.",
                icon: "hand.raised.fill",
                tone: "danger"
            )
        }
        if state.pageKind == "login" || state.residuals.contains("login_required") {
            return WebsiteGuidedStep(
                title: "Recover session",
                detail: "This page looks like a login or footer state. Try the app bridge if you are logged in there, or use neutral web search to find a better landing page.",
                icon: "person.crop.circle.badge.exclamationmark",
                tone: "warning"
            )
        }
        if state.pageKind == "blocked_or_bot_check" || state.residuals.contains("bot_check_or_captcha") {
            return WebsiteGuidedStep(
                title: "Use another bridge",
                detail: "This looks like a blocker or bot-check. Memla should not bypass it; try app bridge or neutral web search.",
                icon: "exclamationmark.triangle.fill",
                tone: "warning"
            )
        }
        if state.safeActions.contains("fill_search_query") {
            return WebsiteGuidedStep(
                title: "Fill the search box",
                detail: "A search-like input is visible. Use the safe search primitive to fill the capsule query before selecting a result.",
                icon: "magnifyingglass",
                tone: "safe"
            )
        }
        if state.pageKind == "cart" {
            return WebsiteGuidedStep(
                title: "Verify cart, then enter checkout",
                detail: "Cart state is visible. Verify item, modifiers, tip, address, and total. If it matches, use Enter Checkout; final purchase still remains blocked.",
                icon: "cart.badge.questionmark",
                tone: "warning"
            )
        }
        if state.pageKind == "menu_or_item" {
            return WebsiteGuidedStep(
                title: "Review item funnel",
                detail: "Item/menu controls are visible. Match the item and modifiers, then use Tap Reviewed for add/customize/cart steps.",
                icon: "list.bullet.rectangle",
                tone: "safe"
            )
        }
        if let best = state.candidates.first(where: { !$0.blocked && !$0.url.isEmpty && $0.score > 0 }) {
            return WebsiteGuidedStep(
                title: "Open ranked candidate",
                detail: "\(best.label) matches the capsule best right now. Open it, then Memla will inspect the next page.",
                icon: "link",
                tone: "safe"
            )
        }
        if let button = state.candidates.first(where: { $0.kind == "button" && $0.url.isEmpty && $0.tapSafety == "safe" }) {
            return WebsiteGuidedStep(
                title: "Tap safe button",
                detail: "\(button.label) is classified as a non-final control. Tap it only if it matches the current step.",
                icon: "hand.tap",
                tone: "safe"
            )
        }
        if let button = state.candidates.first(where: { $0.kind == "button" && $0.url.isEmpty && $0.tapSafety == "caution" }) {
            return WebsiteGuidedStep(
                title: "Review candidate tap",
                detail: "\(button.label) needs human review first. If this is the intended item/control, use Tap Reviewed.",
                icon: "hand.tap",
                tone: "warning"
            )
        }
        if state.residuals.contains("target_restaurant_not_visible") || state.residuals.contains("target_item_not_visible") {
            return WebsiteGuidedStep(
                title: "Find a better page",
                detail: "The capsule target is not visible here. Use the bridge suggestions or search again before opening candidates.",
                icon: "arrow.triangle.branch",
                tone: "warning"
            )
        }
        if !state.candidates.isEmpty {
            return WebsiteGuidedStep(
                title: "Review visible candidates",
                detail: "Memla found page candidates but none strongly match the capsule yet. Prefer search or user review before opening.",
                icon: "rectangle.stack.badge.person.crop",
                tone: "neutral"
            )
        }
        return WebsiteGuidedStep(
            title: "Continue inspection",
            detail: "This page does not expose a clear next action yet. Navigate or search, then inspect again.",
            icon: "scope",
            tone: "neutral"
        )
    }

    private func guidanceColor(_ tone: String) -> Color {
        switch tone {
        case "safe":
            return .green
        case "warning":
            return .orange
        case "danger":
            return .red
        default:
            return .blue
        }
    }

    private func searchQueryIfAvailable(for state: WebsiteC2AState) -> String? {
        let query = commerceSearchQuery(from: route.capsule)
        guard !query.isEmpty else {
            return nil
        }
        let exposesSearch = state.safeActions.contains("fill_search_query")
            || state.pageKind == "search_form"
            || state.inputs.contains { $0.lowercased().contains("search") }
        return exposesSearch ? query : nil
    }

    private func commerceSearchQuery(from capsule: ActionCapsule?) -> String {
        guard let capsule = capsule else {
            return ""
        }
        let restaurant = capsule.slots["restaurant"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let item = capsule.slots["item"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if restaurant.isEmpty {
            return item
        }
        if item.isEmpty {
            return restaurant
        }
        if restaurant.lowercased().contains(item.lowercased()) {
            return restaurant
        }
        return "\(restaurant) \(item)"
    }

    private func bridgeSuggestions(for state: WebsiteC2AState) -> [WebsiteBridgeSuggestion] {
        guard let capsule = route.capsule else {
            return []
        }
        var suggestions: [WebsiteBridgeSuggestion] = []
        var seen = Set<String>()

        func add(optionID: String, reason: String) {
            guard let option = capsule.bridgeOptions.first(where: { $0.optionID == optionID }),
                  !seen.contains(option.optionID) else {
                return
            }
            seen.insert(option.optionID)
            suggestions.append(WebsiteBridgeSuggestion(id: option.optionID, option: option, reason: reason))
        }

        if state.pageKind == "login" || state.residuals.contains("login_required") {
            add(optionID: "service_app", reason: "Login state detected, so the installed app may have the best session.")
            add(optionID: "generic_web_search", reason: "Neutral web search can recover when the service URL lands in login/footer state.")
        }
        if state.pageKind == "blocked_or_bot_check" || state.residuals.contains("bot_check_or_captcha") {
            add(optionID: "generic_web_search", reason: "Bot-check state detected, so try a neutral web search instead.")
            add(optionID: "service_app", reason: "The app bridge may avoid this web blocker.")
        }
        if state.residuals.contains("target_restaurant_not_visible") || state.residuals.contains("target_item_not_visible") {
            add(optionID: "generic_web_search", reason: "Target terms are not visible on this page, so search the open web.")
        }
        return suggestions
    }

    private func handleAutoDriveUpdate(for state: WebsiteC2AState) {
        guard autoDriveEnabled, (state.pageKind.hasPrefix("dd_") || state.pageKind.hasPrefix("ue_") || state.pageKind.hasPrefix("ub_")) else {
            return
        }
        guard !browser.isLoading, !browser.isInspecting, !browser.isRunningButtonAction else {
            return
        }

        let signature = doorDashAutoDriveSignature(for: state)
        let candidates = mirrorCandidates(for: state)
        let doorDashPlan = state.pageKind == "dd_item_modal"
            ? planDoorDashCustomizerWorkflow(from: candidates, state: state)
            : nil
        if let doorDashPlan {
            maybeTraceDoorDashWorkflowPlan(doorDashPlan)
        } else {
            lastDoorDashPlannerMarker = ""
        }

        if !pendingStepActionRole.isEmpty {
            if pendingStepTapAcknowledged, pendingDoorDashStepConfirmed(in: state, signature: signature) {
                appendAgencyTrace("DoorDash step confirmed from mirror.")
                applyPendingDoorDashStepSuccess()
                clearPendingStepAction()
                lastAutoDriveSignature = ""
                lastDoorDashPlannerMarker = ""
            } else {
                let pendingSeconds = Date().timeIntervalSince(pendingStepActionAt)
                if !pendingStepTapAcknowledged,
                   pendingStepTapRetryCount < 1,
                   pendingSeconds >= 1.15,
                   let retryCandidate = pendingDoorDashRetryCandidate(in: state) {
                    pendingStepTapRetryCount += 1
                    autoDriveStatus = "Retrying \(retryCandidate.label)..."
                    appendAgencyTrace("DoorDash tap was not acknowledged. Retrying \(retryCandidate.label) once.")
                    sendBrowserDebugSnapshot(reason: "pending_step_retry:\(retryCandidate.role):\(retryCandidate.label)", state: state, force: true)
                    let actionEpoch = autoDriveEpoch
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                        guard actionEpoch == autoDriveEpoch, autoDriveEnabled else {
                            return
                        }
                        performAutoDriveAction(retryCandidate, allowCaution: true)
                    }
                    lastAutoDriveSignature = signature
                    return
                }
                let confirmationDeadline = pendingStepActionRole == "dd_modifier_save" ? 4.8 : 4.0
                if pendingSeconds >= confirmationDeadline {
                    appendAgencyTrace("DoorDash step never confirmed from mirror. Re-planning from current state.")
                    sendBrowserDebugSnapshot(reason: "pending_step_timeout", state: state)
                    rollbackPendingDoorDashStepFailure()
                    lastAutoDriveSignature = ""
                    lastDoorDashPlannerMarker = ""
                } else {
                    autoDriveStatus = pendingStepTapAcknowledged
                        ? "Waiting for DoorDash mirror confirmation..."
                        : "Waiting for DoorDash customizer transition..."
                    appendAgencyTrace(autoDriveStatus)
                    lastAutoDriveSignature = signature
                    return
                }
            }
        }

        if state.pageKind == "dd_payment_sheet" || state.pageKind == "dd_checkout" || state.pageKind == "ue_checkout" || state.pageKind == "ub_product_selection" {
            pendingDoorDashRole = ""
            pendingDoorDashLabel = ""
            addToCartRetryCount = 0
            autoDriveStatus = state.pageKind == "ub_product_selection"
                ? "Uber ride is priced. Waiting for your final request confirmation."
                : "Reached checkout. Waiting for your final confirmation."
            appendAgencyTrace(autoDriveStatus)
            lastAutoDriveSignature = signature
            return
        }

        if state.authState == "login_required" {
            autoDriveStatus = "Waiting for you to sign in."
            appendAgencyTrace(autoDriveStatus)
            lastAutoDriveSignature = signature
            return
        }

        if pendingDoorDashRole == "dd_add_to_cart" || pendingDoorDashRole == "ue_add_to_cart" {
            if (state.pageKind == "dd_item_modal" || state.pageKind == "ue_item_modal"),
               let retryCandidate = candidates.first(where: { $0.role == pendingDoorDashRole && !$0.blocked }),
               addToCartRetryCount < 1 {
                addToCartRetryCount += 1
                autoDriveStatus = "Retrying Add to cart..."
                appendAgencyTrace(autoDriveStatus)
                let actionEpoch = autoDriveEpoch
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    guard actionEpoch == autoDriveEpoch, autoDriveEnabled else {
                        return
                    }
                    performAutoDriveAction(retryCandidate, allowCaution: true)
                }
                return
            }
            if state.pageKind == "dd_cart_drawer"
                || state.pageKind == "dd_cart_page"
                || state.pageKind == "ue_cart_page"
                || candidates.contains(where: { ["dd_continue_cta", "dd_cart_cta", "ue_continue_cta", "ue_cart_cta"].contains($0.role) }) {
                finalizePendingFoodAdd()
            } else if pendingDoorDashRole == "dd_add_to_cart", state.pageKind == "dd_storefront" {
                autoDriveStatus = "Verifying cart update after add..."
                appendAgencyTrace(autoDriveStatus)
                finalizePendingFoodAdd()
                lastAutoDriveSignature = ""
            } else if pendingDoorDashRole == "dd_add_to_cart" {
                autoDriveStatus = "Waiting for cart confirmation..."
                appendAgencyTrace(autoDriveStatus)
                lastAutoDriveSignature = signature
                return
            } else if pendingDoorDashRole == "ue_add_to_cart" {
                autoDriveStatus = "Waiting for order confirmation..."
                appendAgencyTrace(autoDriveStatus)
                lastAutoDriveSignature = signature
                return
            }
        }

        if pendingDoorDashRole == "ub_fill_destination" {
            if candidates.contains(where: { $0.role == "ub_dropoff_result" }) || candidates.contains(where: { $0.role == "ub_see_prices_cta" }) {
                pendingDoorDashRole = ""
                pendingDoorDashLabel = ""
            } else if addToCartRetryCount < 1,
                      let destination = route.capsule?.slots["destination"]?.trimmingCharacters(in: .whitespacesAndNewlines),
                      !destination.isEmpty {
                addToCartRetryCount += 1
                autoDriveStatus = "Retrying destination entry..."
                appendAgencyTrace(autoDriveStatus)
                let actionEpoch = autoDriveEpoch
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) {
                    guard actionEpoch == autoDriveEpoch, autoDriveEnabled else {
                        return
                    }
                    browser.fillUberRideLocation(destination, isPickup: false, capsule: route.capsule)
                }
                return
            } else {
                pendingDoorDashRole = ""
                pendingDoorDashLabel = ""
                addToCartRetryCount = 0
            }
        }

        guard signature != lastAutoDriveSignature else {
            return
        }

        if state.pageKind == "ub_trip_builder",
           state.serviceFacts["ub_pickup_missing"] != "true",
           !candidates.contains(where: { $0.role == "ub_dropoff_result" }),
           let destination = route.capsule?.slots["destination"]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !destination.isEmpty,
           state.serviceFacts["ub_dropoff_missing"] == "true" {
            lastAutoDriveSignature = signature
            pendingDoorDashRole = "ub_fill_destination"
            pendingDoorDashLabel = destination
            addToCartRetryCount = 0
            autoDriveStatus = "Typing destination..."
            appendAgencyTrace(autoDriveStatus)
            let actionEpoch = autoDriveEpoch
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                guard actionEpoch == autoDriveEpoch, autoDriveEnabled else {
                    return
                }
                browser.fillUberRideLocation(destination, isPickup: false, capsule: route.capsule)
            }
            return
        }

        guard let action = doorDashAutoAction(for: state, candidates: candidates) else {
            lastAutoDriveSignature = signature
            if let doorDashPlan {
                let group = readableDoorDashGroupKind(doorDashPlan.snapshot.activeGroupKind)
                let focus = readableDoorDashFocusKind(doorDashPlan.focusKind)
                autoDriveStatus = focus == "waiting"
                    ? "Waiting for DoorDash customizer transition..."
                    : "Waiting on DoorDash \(focus) in \(group)..."
                if state.pageKind == "dd_item_modal" {
                    sendBrowserDebugSnapshot(reason: "customizer_no_action:\(focus):\(group)", state: state)
                }
            } else if state.pageKind == "dd_storefront" {
                autoDriveStatus = "Waiting for DoorDash menu items..."
            } else if state.pageKind == "ue_storefront" {
                autoDriveStatus = "Waiting for Uber Eats menu items..."
            } else if state.pageKind == "ub_trip_builder" {
                autoDriveStatus = "Waiting for Uber trip fields..."
            } else {
                autoDriveStatus = "Agency is waiting on \(state.pageKind)."
            }
            appendAgencyTrace(autoDriveStatus)
            return
        }

        let normalizedActionLabel = normalizedCommerceTerm(action.candidate.label)
        if action.candidate.role == "dd_modifier_option",
           !normalizedActionLabel.isEmpty,
           normalizedActionLabel == normalizedCommerceTerm(lastModifierSelectionLabel),
           Date().timeIntervalSince(lastModifierSelectionAt) < 1.6 {
            lastAutoDriveSignature = signature
            autoDriveStatus = "Waiting for DoorDash customizer transition..."
            appendAgencyTrace(autoDriveStatus)
            sendBrowserDebugSnapshot(reason: "customizer_duplicate_wait:\(action.candidate.label)", state: state)
            return
        }

        lastAutoDriveSignature = signature
        autoDriveStatus = action.status
        if action.candidate.role == "dd_modifier_option" {
            recordPendingDoorDashStep(
                role: action.candidate.role,
                label: action.candidate.label,
                candidate: action.candidate,
                signature: signature,
                state: state,
                consumedTerms: Set(action.consumedTerms),
                commitKind: action.consumedTerms.isEmpty ? "prerequisite" : "requested"
            )
        } else if action.candidate.role == "dd_modifier_save" {
            recordPendingDoorDashStep(
                role: action.candidate.role,
                label: action.candidate.label,
                candidate: action.candidate,
                signature: signature,
                state: state,
                consumedTerms: [],
                commitKind: "save"
            )
        } else {
            clearPendingStepAction()
        }
        appendAgencyTrace("Action: \(action.candidate.role) → \(action.candidate.label)")
        if state.pageKind == "dd_item_modal",
           ["dd_modifier_option", "dd_modifier_save", "dd_add_to_cart"].contains(action.candidate.role) {
            sendBrowserDebugSnapshot(reason: "pre_action:\(action.candidate.role):\(action.candidate.label)", state: state, force: true)
        }
        if action.candidate.role == "dd_item_card", !primaryFoodItemAdded {
            inProgressPrimaryItemLabel = action.candidate.label
        }
        if action.pendingRole == "dd_add_to_cart" || action.pendingRole == "ue_add_to_cart" {
            pendingDoorDashRole = action.pendingRole
            pendingDoorDashLabel = action.candidate.label
            addToCartRetryCount = 0
            pendingFoodAddOperation = primaryFoodItemAdded ? "addon" : "primary"
            preferCartProgress = pendingFoodAddOns.isEmpty && primaryFoodItemAdded
        }
        let autoDriveDelay: TimeInterval
        switch action.candidate.role {
        case "ub_pickup_input", "ub_pickup_current_location":
            autoDriveDelay = 0.8
        case "ub_dropoff_input":
            autoDriveDelay = 0.65
        default:
            autoDriveDelay = 0.45
        }
        let actionEpoch = autoDriveEpoch
        DispatchQueue.main.asyncAfter(deadline: .now() + autoDriveDelay) {
            guard actionEpoch == autoDriveEpoch, autoDriveEnabled else {
                return
            }
            performAutoDriveAction(action.candidate, allowCaution: action.allowCaution)
        }
    }

    private func doorDashAutoDriveSignature(for state: WebsiteC2AState) -> String {
        let candidateSlice = mirrorCandidates(for: state)
            .prefix(4)
            .map { "\($0.role):\($0.label)" }
            .joined(separator: "|")
        let doorDashLayerState = [
            state.serviceFacts["dd_active_layer"] ?? "",
            state.serviceFacts["dd_active_group_key"] ?? "",
            state.serviceFacts["dd_active_group_label"] ?? "",
            state.serviceFacts["dd_active_group_required"] ?? ""
        ].joined(separator: "|")
        let agencyState = [
            primaryFoodItemAdded ? "primary_added" : "primary_pending",
            inProgressPrimaryItemLabel,
            pendingFoodAddOns.first ?? "",
            completedModifierTerms.sorted().joined(separator: ","),
            inFlightModifierTerms.sorted().joined(separator: ","),
            traversedDoorDashDerivedGroups
                .map(\.rawValue)
                .sorted()
                .joined(separator: ","),
            doorDashModifierCommitPending ? "commit_pending" : "commit_clear",
            doorDashPendingCommitKind
        ].joined(separator: "|")
        return [state.pageKind, browser.currentURL, doorDashLayerState, candidateSlice, agencyState].joined(separator: "||")
    }

    private func doorDashAutoAction(for state: WebsiteC2AState, candidates: [WebsiteC2ACandidate]) -> MirrorAutoDriveAction? {
        switch state.pageKind {
        case "ub_trip_builder":
            let pickupMissing = state.serviceFacts["ub_pickup_missing"] == "true"
            let dropoffMissing = state.serviceFacts["ub_dropoff_missing"] == "true"
            if state.serviceFacts["ub_pickup_missing"] == "true" {
                if let pickupResult = candidates.first(where: { $0.role == "ub_pickup_result" && !$0.blocked }) {
                    return MirrorAutoDriveAction(
                        candidate: pickupResult,
                        allowCaution: true,
                        status: "Using current pickup location...",
                        pendingRole: ""
                    )
                }
                if let pickupInput = candidates.first(where: { $0.role == "ub_pickup_input" && !$0.blocked }) {
                    return MirrorAutoDriveAction(
                        candidate: pickupInput,
                        allowCaution: true,
                        status: "Opening pickup field...",
                        pendingRole: ""
                    )
                }
                if let pickupLocation = candidates.first(where: { $0.role == "ub_pickup_current_location" && !$0.blocked }) {
                    return MirrorAutoDriveAction(
                        candidate: pickupLocation,
                        allowCaution: true,
                        status: "Using current location...",
                        pendingRole: ""
                    )
                }
            }
            if let dropoffResult = candidates.first(where: { $0.role == "ub_dropoff_result" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: dropoffResult,
                    allowCaution: true,
                    status: "Choosing destination...",
                    pendingRole: ""
                )
            }
            if !pickupMissing && !dropoffMissing,
               let seePrices = candidates.first(where: { $0.role == "ub_see_prices_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: seePrices,
                    allowCaution: seePrices.tapSafety == "caution",
                    status: "Getting ride prices...",
                    pendingRole: ""
                )
            }
        case "ue_entry_gate":
            if let continueBrowser = candidates.first(where: { $0.role == "ue_continue_browser" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: continueBrowser,
                    allowCaution: true,
                    status: "Continuing in browser...",
                    pendingRole: ""
                )
            }
            if let address = candidates.first(where: { $0.role == "ue_address_result" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: address,
                    allowCaution: true,
                    status: "Selecting delivery address...",
                    pendingRole: ""
                )
            }
        case "ue_search_results":
            if let store = candidates.first(where: { $0.role == "ue_store_card" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: store,
                    allowCaution: false,
                    status: "Opening \(store.label)...",
                    pendingRole: ""
                )
            }
        case "ue_storefront":
            if preferCartProgress,
               let cart = candidates.first(where: { $0.role == "ue_cart_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: cart,
                    allowCaution: cart.tapSafety == "caution",
                    status: "Opening cart...",
                    pendingRole: ""
                )
            }
            if let targetedItem = bestCandidate(role: "ue_item_card", in: candidates, targetTerms: currentFoodTargetTerms()) {
                return MirrorAutoDriveAction(
                    candidate: targetedItem.candidate,
                    allowCaution: targetedItem.candidate.tapSafety == "caution",
                    status: "Opening \(targetedItem.candidate.label)...",
                    pendingRole: ""
                )
            }
            if let item = candidates.first(where: { $0.role == "ue_item_card" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: item,
                    allowCaution: item.tapSafety == "caution",
                    status: "Opening \(item.label)...",
                    pendingRole: ""
                )
            }
            if let add = candidates.first(where: { $0.role == "ue_add_to_cart" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: add,
                    allowCaution: true,
                    status: "Adding item to order...",
                    pendingRole: "ue_add_to_cart"
                )
            }
        case "ue_item_modal":
            if let add = candidates.first(where: { $0.role == "ue_add_to_cart" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: add,
                    allowCaution: true,
                    status: "Adding item to order...",
                    pendingRole: "ue_add_to_cart"
                )
            }
        case "ue_cart_page":
            if let next = candidates.first(where: { $0.role == "ue_continue_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: next,
                    allowCaution: true,
                    status: "Continuing to checkout...",
                    pendingRole: ""
                )
            }
            if let cart = candidates.first(where: { $0.role == "ue_cart_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: cart,
                    allowCaution: cart.tapSafety == "caution",
                    status: "Opening cart...",
                    pendingRole: ""
                )
            }
        case "dd_search_results":
            if let store = candidates.first(where: { $0.role == "dd_store_card" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: store,
                    allowCaution: false,
                    status: "Opening \(store.label)...",
                    pendingRole: ""
                )
            }
        case "dd_storefront":
            let unfinishedPrimaryCustomizer = !primaryFoodItemAdded
                && !inProgressPrimaryItemLabel.isEmpty
                && (!completedModifierTerms.isEmpty
                    || !inFlightModifierTerms.isEmpty
                    || doorDashModifierCommitPending
                    || pendingStepActionRole.hasPrefix("dd_modifier"))
            if primaryFoodItemAdded, !pendingFoodAddOns.isEmpty,
               let targetedAddOn = bestCandidate(role: "dd_item_card", in: candidates, targetTerms: currentFoodTargetTerms()) {
                return MirrorAutoDriveAction(
                    candidate: targetedAddOn.candidate,
                    allowCaution: targetedAddOn.candidate.tapSafety == "caution",
                    status: "Opening \(targetedAddOn.candidate.label)...",
                    pendingRole: ""
                )
            }
            if primaryFoodItemAdded, !pendingFoodAddOns.isEmpty {
                return nil
            }
            if primaryFoodItemAdded, pendingFoodAddOns.isEmpty {
                if let cart = candidates.first(where: { $0.role == "dd_cart_cta" && !$0.blocked }) {
                    return MirrorAutoDriveAction(
                        candidate: cart,
                        allowCaution: cart.tapSafety == "caution",
                        status: "Opening cart...",
                        pendingRole: ""
                    )
                }
                return nil
            }
            if preferCartProgress,
               let cart = candidates.first(where: { $0.role == "dd_cart_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: cart,
                    allowCaution: cart.tapSafety == "caution",
                    status: "Opening cart...",
                    pendingRole: ""
                )
            }
            if let targetedItem = bestCandidate(role: "dd_item_card", in: candidates, targetTerms: currentFoodTargetTerms()) {
                return MirrorAutoDriveAction(
                    candidate: targetedItem.candidate,
                    allowCaution: targetedItem.candidate.tapSafety == "caution",
                    status: "Opening \(targetedItem.candidate.label)...",
                    pendingRole: ""
                )
            }
            if unfinishedPrimaryCustomizer {
                return nil
            }
            if let item = candidates.first(where: { $0.role == "dd_item_card" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: item,
                    allowCaution: item.tapSafety == "caution",
                    status: "Opening \(item.label)...",
                    pendingRole: ""
                )
            }
            if let add = candidates.first(where: { $0.role == "dd_add_to_cart" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: add,
                    allowCaution: true,
                    status: "Adding item to cart...",
                    pendingRole: "dd_add_to_cart"
                )
            }
        case "dd_item_modal":
            let plan = planDoorDashCustomizerWorkflow(from: candidates, state: state)
            guard let transition = plan.nextTransition, let candidate = transition.candidate else {
                return nil
            }
            switch transition.kind {
            case .requestedModifier:
                return MirrorAutoDriveAction(
                    candidate: candidate,
                    allowCaution: true,
                    status: "Selecting \(candidate.label)...",
                    pendingRole: "",
                    consumedTerms: transition.consumedTerms
                )
            case .prerequisiteModifier:
                return MirrorAutoDriveAction(
                    candidate: candidate,
                    allowCaution: true,
                    status: "Continuing through \(candidate.label)...",
                    pendingRole: ""
                )
            case .saveStep:
                return MirrorAutoDriveAction(
                    candidate: candidate,
                    allowCaution: true,
                    status: "Saving options...",
                    pendingRole: ""
                )
            case .reviewStep:
                guard plan.plannerState.addToCartAllowed else {
                    return nil
                }
                return MirrorAutoDriveAction(
                    candidate: candidate,
                    allowCaution: true,
                    status: "Adding item to cart...",
                    pendingRole: "dd_add_to_cart"
                )
            case .waiting:
                return nil
            }
        case "dd_cart_drawer", "dd_cart_page":
            if !pendingFoodAddOns.isEmpty,
               let close = candidates.first(where: { $0.role == "dd_modal_close" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: close,
                    allowCaution: true,
                    status: "Returning to menu for \(pendingFoodAddOns.first ?? "add on")...",
                    pendingRole: ""
                )
            }
            if let checkout = candidates.first(where: { $0.role == "dd_continue_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: checkout,
                    allowCaution: true,
                    status: "Continuing to checkout...",
                    pendingRole: ""
                )
            }
            if let cart = candidates.first(where: { $0.role == "dd_cart_cta" && !$0.blocked }) {
                return MirrorAutoDriveAction(
                    candidate: cart,
                    allowCaution: cart.tapSafety == "caution",
                    status: "Opening cart...",
                    pendingRole: ""
                )
            }
        default:
            break
        }
        return nil
    }

    private func performAutoDriveAction(_ candidate: WebsiteC2ACandidate, allowCaution: Bool) {
        if candidate.role == "dd_continue_cta" {
            appendAgencyTrace("Tap: \(candidate.label)")
            tapCandidate(candidate, allowCaution: true)
            return
        }
        if !candidate.url.isEmpty {
            appendAgencyTrace("Open: \(candidate.label)")
            openCandidate(candidate)
        } else {
            appendAgencyTrace("Tap: \(candidate.label)")
            tapCandidate(candidate, allowCaution: allowCaution)
        }
    }

    private func openCandidate(_ candidate: WebsiteC2ACandidate) {
        if candidate.role == "dd_continue_cta" {
            tapCandidate(candidate, allowCaution: true)
            return
        }
        guard !candidate.blocked, let url = URL(string: candidate.url) else {
            return
        }
        let scheme = url.scheme?.lowercased() ?? ""
        if scheme == "http" || scheme == "https" {
            browser.navigate(to: url, autoInspect: true, capsule: route.capsule)
            return
        }
        UIApplication.shared.open(url)
    }

    private func tapCandidate(_ candidate: WebsiteC2ACandidate, allowCaution: Bool = false) {
        if candidate.role == "ub_pickup_input" {
            browser.focusUberRideField(isPickup: true, capsule: route.capsule)
            return
        }
        if candidate.role == "ub_pickup_current_location" {
            browser.focusUberRideField(isPickup: true, capsule: route.capsule)
            return
        }
        if candidate.role == "ub_dropoff_input" {
            browser.focusUberRideField(isPickup: false, capsule: route.capsule)
            return
        }
        if candidate.role == "dd_modifier_option" {
            browser.tapDoorDashResolvedModifierOption(candidate, capsule: route.capsule)
            return
        }
        if candidate.role == "dd_modifier_save" {
            browser.tapDoorDashModifierSave(capsule: route.capsule)
            return
        }
        if candidate.role == "dd_add_to_cart", browser.websiteState?.pageKind == "dd_item_modal" {
            browser.tapDoorDashAddToCart(capsule: route.capsule)
            return
        }
        if candidate.role == "dd_continue_cta" {
            browser.tapDoorDashContinueToCheckout(capsule: route.capsule)
            return
        }
        browser.tapButtonCandidate(candidate, allowCaution: allowCaution, capsule: route.capsule)
    }

    private func copyDebugSnapshot(_ state: WebsiteC2AState) {
        UIPasteboard.general.string = debugSnapshotText(for: state)
        debugCopyStatus = "Copied debug snapshot."
    }

    private func copyAgencyTrace() {
        UIPasteboard.general.string = agencyTraceText()
        debugCopyStatus = "Copied agency trace."
    }

    private func sendBrowserDebugSnapshot(reason: String, state: WebsiteC2AState?, force: Bool = false) {
        let resolvedState = state ?? browser.websiteState
        let marker = [
            reason,
            browser.currentURL,
            resolvedState?.pageKind ?? "",
            pendingStepActionRole,
            pendingStepActionLabel,
            autoDriveStatus
        ].joined(separator: "||")
        if !force, marker == lastDebugUploadMarker {
            return
        }
        lastDebugUploadMarker = marker
        let baseURL = UserDefaults.standard.string(forKey: "memlaBaseURL")?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !baseURL.isEmpty else {
            debugUploadStatus = "No Memla server URL is saved, so debug upload is unavailable."
            return
        }
        let topCandidates = Array((resolvedState?.candidates ?? []).prefix(10)).map { candidate in
            MemlaBrowserDebugCandidate(
                role: candidate.role,
                label: candidate.label,
                score: candidate.score,
                groupKey: candidate.groupKey,
                groupLabel: candidate.groupLabel,
                selected: candidate.isSelected,
                opensSubflow: candidate.opensSubflow
            )
        }
        let pendingStep: [String: String] = [
            "role": pendingStepActionRole,
            "label": pendingStepActionLabel,
            "commit_kind": pendingStepCommitKind,
            "target_group_key": pendingStepTargetGroupKey,
            "target_group_label": pendingStepTargetGroupLabel,
            "target_opens_subflow": pendingStepTargetOpensSubflow ? "true" : "false",
            "tap_acknowledged": pendingStepTapAcknowledged ? "true" : "false",
            "tap_verified": pendingStepTapVerifiedSelection ? "true" : "false",
            "observed_group_key": pendingStepObservedGroupKey,
            "observed_group_label": pendingStepObservedGroupLabel,
            "seconds_since_action": pendingStepActionAt == .distantPast ? "" : String(format: "%.2f", Date().timeIntervalSince(pendingStepActionAt))
        ]
        let payload = MemlaBrowserDebugRequest(
            source: "ios_browser",
            reason: reason,
            title: browser.pageTitle,
            url: browser.currentURL,
            pageKind: resolvedState?.pageKind ?? "",
            pageSummary: resolvedState?.summary ?? "",
            authState: resolvedState?.authState ?? "",
            inspectionStatus: browser.inspectionStatus,
            buttonActionStatus: browser.buttonActionStatus,
            autoDriveEnabled: autoDriveEnabled,
            autoDriveStatus: autoDriveStatus,
            residuals: resolvedState?.residuals ?? [],
            safeActions: resolvedState?.safeActions ?? [],
            serviceFacts: resolvedState?.serviceFacts ?? [:],
            pendingStep: pendingStep,
            topCandidates: topCandidates,
            agencyTrace: Array(agencyTrace.reversed()),
            mirrorDebugText: resolvedState.map { debugSnapshotText(for: $0) } ?? "",
            agencyTraceText: agencyTraceText()
        )
        Task {
            do {
                _ = try await MemlaClient.shared.debugBrowser(payload: payload, baseURL: baseURL)
                await MainActor.run {
                    debugUploadStatus = "Sent debug snapshot to Memla server."
                }
            } catch {
                await MainActor.run {
                    debugUploadStatus = "Debug upload failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func debugSnapshotText(for state: WebsiteC2AState) -> String {
        var lines: [String] = []
        lines.append("Memla Mirror Debug Snapshot")
        lines.append("Title: \(browser.pageTitle)")
        lines.append("URL: \(browser.currentURL)")
        lines.append("PageKind: \(state.pageKind)")
        lines.append("Summary: \(state.summary)")
        lines.append("Auth: \(state.authState)")
        if !state.residuals.isEmpty {
            lines.append("Residuals: \(state.residuals.joined(separator: ", "))")
        }
        if !state.safeActions.isEmpty {
            lines.append("SafeActions: \(state.safeActions.joined(separator: ", "))")
        }
        lines.append("Candidates:")
        for candidate in state.candidates {
            let score = String(format: "%.1f", candidate.score)
            let detail = [
                "[\(candidate.role)]",
                candidate.label,
                "score=\(score)",
                "kind=\(candidate.kind)",
                "tap=\(candidate.tapSafety)",
                "reason=\(candidate.reason)"
            ].joined(separator: " | ")
            lines.append(detail)
        }
        return lines.joined(separator: "\n")
    }

    private func agencyTraceText() -> String {
        var lines: [String] = []
        lines.append("Memla Agency Trace")
        lines.append("Title: \(browser.pageTitle)")
        lines.append("URL: \(browser.currentURL)")
        lines.append("AutoDrive: \(autoDriveEnabled ? "enabled" : "disabled")")
        lines.append("Status: \(autoDriveStatus)")
        lines.append("Trace:")
        if agencyTrace.isEmpty {
            lines.append("(empty)")
        } else {
            lines.append(contentsOf: agencyTrace.reversed())
        }
        return lines.joined(separator: "\n")
    }

    private func openBridgeOption(_ option: ActionBridgeOption) {
        guard let url = URL(string: option.url) else {
            return
        }
        if option.kind == "in_app_web" {
            browser.navigate(to: url, autoInspect: true, capsule: route.capsule)
            return
        }
        UIApplication.shared.open(url)
    }

    private func readableRequirement(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
