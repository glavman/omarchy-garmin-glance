pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.Panel {
  id: root
  manageIpc: false
  property Item anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property real stepGoal: { var n = Number(setting("stepGoal", 10000)); return isFinite(n) && n > 0 ? n : 10000 }
  property bool showDetails: false
  property bool cursorActive: false
  property string focusSection: "stats"
  property int focusIndex: 0
  property string contextSection: "stats"
  property int contextIndex: 0
  property string historyKey: "steps"
  readonly property var fields: [
    {key: "steps", title: "Steps", historyTitle: "Steps", unit: ""},
    {key: "bodyBattery", title: "Body battery", historyTitle: "Battery peak", unit: ""},
    {key: "sleep", title: "Sleep score", historyTitle: "Sleep", unit: ""},
    {key: "sleepDuration", title: "Sleep time", historyTitle: "Sleep time", unit: ""},
    {key: "hrv", title: "HRV (ms)", historyTitle: "HRV / Resting HR", unit: ""},
    {key: "restingHeartRate", title: "Resting HR (bpm)", historyTitle: "Resting HR", unit: ""},
    {key: "stress", title: "Stress", historyTitle: "Stress", unit: ""}
  ]
  readonly property var historyFields: fields.filter(function(field) { return ["sleepDuration", "restingHeartRate", "bodyBattery"].indexOf(field.key) < 0 })
    .concat(fields.filter(function(field) { return field.key === "bodyBattery" }))
  readonly property var payload: service && service.payload && service.payload.schemaVersion === 1 ? service.payload : ({})
  readonly property var metrics: Object.assign({}, payload.metrics || {}, payload.wellness || {})
  readonly property var dailyHistory: Object.assign({}, payload.history || {}, payload.supplementalHistory || {})
  readonly property bool supplementalSelected: historyKey === "stress"
  readonly property var activity: payload.latestActivity || null
  readonly property var activities: payload.activities || null
  readonly property var activitiesOverview: Model.activitiesOverview(activities)
  property int activityLimit: 10
  readonly property var visibleActivities: activities ? activities.items.slice(0, activityLimit) : []
  readonly property bool moreActivities: !!activities && visibleActivities.length < activities.items.length
  readonly property bool activitiesCached: !!activities && (cached || !!payload.activitiesError
    || !Model.validTime(payload.activitiesFetchedAt) || now - Date.parse(payload.activitiesFetchedAt) > 3600000)
  readonly property string activitiesDateLabel: activities ? activities.startDate + " to " + activities.endDate + " / 7 days" : "7 days including today"
  readonly property string activitiesStatus: {
    var parts = []
    if (busy) parts.push("Refreshing activities...")
    if (payload.activitiesError) parts.push("Activities unavailable (" + payload.activitiesError + ")" + (activities ? "; showing cached results" : ""))
    else if (!activities) parts.push(busy ? "Waiting for results" : "Waiting for activities")
    if (activitiesCached) parts.push("Cached")
    if (activities && !activities.items.length) parts.push("No recorded activities in this period")
    return parts.join(" / ")
  }
  readonly property bool busy: !!service && service.busy
  readonly property real now: service ? service.now : Date.now()
  readonly property bool cached: payload.status === "cached" || (!!payload.fetchedAt && now - Date.parse(payload.fetchedAt) > 3600000)
  readonly property bool historyCached: cached || !!payload.historyError || (!!payload.historyFetchedAt && now - Date.parse(payload.historyFetchedAt) > 3600000)
  readonly property bool activityCached: cached || !!payload.activityError || (!!payload.activityFetchedAt && now - Date.parse(payload.activityFetchedAt) > 3600000)
  readonly property bool supplementalCached: cached || !!payload.supplementalHistoryError || (!!payload.supplementalHistoryFetchedAt && now - Date.parse(payload.supplementalHistoryFetchedAt) > 3600000)
  readonly property var activityDetails: Model.activityDetails(activity)
  readonly property bool canOpenGrafana: !!service && !service.demoMode
  readonly property bool pairedHistory: historyKey === "sleep" || historyKey === "hrv"
  readonly property bool hasActivityGps: !!activity && !!activity.gpsSelector && activity.durationSeconds > 0
  readonly property bool latestActivityContext: contextSection === "activity" || contextSection === "details"
  readonly property bool activityContext: latestActivityContext || contextSection === "activities" || contextSection === "weekly"
  readonly property var contextActivity: latestActivityContext ? activity
    : contextSection === "activities" ? visibleActivities[contextIndex] || null : null
  readonly property bool canOpenContext: activityContext ? canOpenActivity(contextActivity) : canOpenGrafana
  readonly property int footerCount: 3 + (hasActivityGps ? 1 : 0) + (latestActivityContext ? 1 : 0)
  readonly property var sections: ["stats", "selector", "history"]
    .concat(pairedHistory ? ["secondaryHistory"] : [])
    .concat(["stress", "weekly"])
    .concat(visibleActivities.length ? ["activities"] : [])
    .concat(["activity"])
    .concat(activityDetails.length ? ["details"] : [])
    .concat(["footer"])
  readonly property var grafanaContext: {
    if (contextSection === "activity" || contextSection === "details") return {key: "activity"}
    if (contextSection === "stress") return {key: "overlay", from: stressChart.startTime, to: stressChart.endTime}
    if (contextSection === "stats") return {key: fields[Math.min(contextIndex, fields.length - 1)].key, kind: "current", date: ""}
    if (contextSection === "selector") return {key: historyFields[Math.min(contextIndex, historyFields.length - 1)].key, kind: "history", date: ""}
    var secondary = contextSection === "secondaryHistory"
    return {key: secondary ? (historyKey === "sleep" ? "sleepDuration" : "restingHeartRate") : historyKey,
      kind: "history", date: secondary ? secondaryHistoryChart.selectedDate : historyChart.selectedDate}
  }
  readonly property string contextLabel: {
    if (grafanaContext.key === "activity") return "Recent Activity"
    if (grafanaContext.key === "overlay") return "Body battery / stress"
    var field = fields.filter(function(field) { return field.key === root.grafanaContext.key })[0]
    // Dashboard panels may be related views, not the exact displayed statistic.
    return "related " + (field ? (field.key === "hrv" ? "HRV" : field.title.replace(/ \(.*\)/, "")) : "stats")
  }
  readonly property bool currentDay: Model.validTime(payload.sourceDayEnd) && now < Date.parse(payload.sourceDayEnd)
  readonly property string statusText: {
    var parts = []
    if (service && service.demoMode) parts.push("Demo")
    if (!service || !payload.fetchedAt) parts.push("Waiting for data")
    if (service && service.message) parts.push(service.message)
    else if (payload.error) parts.push(Model.errorMessage(payload.error))
    if (cached) parts.push("Cached")
    if (busy) parts.push("Refreshing...")
    if (payload.wellnessError) parts.push("Some daily stats unavailable or cached")
    return parts.join(" / ")
  }
  function stamp(time) {
    return Model.validTime(time) ? Qt.formatDateTime(new Date(time), "ddd d MMM, HH:mm") : ""
  }
  function metricText(key, value) {
    return key === "sleepDuration" ? Model.sleepDuration(value) : Model.numeric(value)
  }
  function activityTotal(total, count, unit) {
    var value = total ? total.value : null
    var text = Model.numeric(value) === "--" ? "--" : unit === "h" ? (value / 3600).toFixed(2)
      : unit === "km" ? (value / 1000).toFixed(2) : Model.numeric(value)
    return text + " " + unit + (total && total.knownCount < count ? " (" + total.knownCount + "/" + count + " known)" : "")
  }
  function canOpenActivity(item) {
    return !!service && !service.demoMode && !!item && Model.validActivityId(item.connectId)
      && typeof service.openActivity === "function"
  }
  function showMoreActivities(reveal) {
    var next = visibleActivities.length
    activityLimit += 10
    setCursor("activities", next, reveal)
  }
  function clampNavigation() {
    if (!sections) return
    var previousSection = focusSection, previousIndex = focusIndex
    if (sections.indexOf(focusSection) < 0) focusSection = focusSection === "activities" ? "weekly" : "history"
    focusIndex = Math.max(0, Math.min(focusIndex, sectionCount(focusSection) - 1))
    if (sections.indexOf(contextSection) < 0) contextSection = contextSection === "activities" ? "weekly" : "history"
    contextIndex = Math.max(0, Math.min(contextIndex, sectionCount(contextSection) - 1))
    if (cursorActive && (focusSection !== previousSection || focusIndex !== previousIndex)) Qt.callLater(revealCursor)
  }
  function switchPanel(direction) {
    return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(hostWidget || root, direction) : false
  }
  function hasCursor(section, index) {
    return cursorActive && focusSection === section && focusIndex === index
  }
  function sectionCount(section) {
    if (section === "stats") return fields.length
    if (section === "selector") return historyFields.length
    if (section === "details") return 1 + (showDetails ? activityDetails.length : 0)
    if (section === "activities") return visibleActivities.length + (moreActivities ? 1 : 0)
    if (section === "footer") return footerCount
    return 1
  }
  function setCursor(section, index, reveal) {
    cursorActive = true
    focusSection = section
    focusIndex = Math.max(0, Math.min(sectionCount(section) - 1, index))
    if (section !== "footer") { contextSection = section; contextIndex = focusIndex }
    if (reveal) { revealGuard.restart(); keys.forceActiveFocus(); Qt.callLater(revealCursor) }
  }
  function hoverCursor(section, index) {
    if (!coach.expanded && !setup.expanded && !revealGuard.running) setCursor(section, index, false)
  }
  function cursorItem() {
    if (focusSection === "stats") return statRows.itemAt(focusIndex)
    if (focusSection === "selector") return selectors.itemAt(focusIndex)
    if (focusSection === "history") return historyChart
    if (focusSection === "secondaryHistory") return secondaryHistoryChart
    if (focusSection === "stress") return stressChart
    if (focusSection === "weekly") return weeklySummary
    if (focusSection === "activities") return focusIndex === visibleActivities.length ? moreActivitiesButton : activityRows.itemAt(focusIndex)
    if (focusSection === "activity") return activitySummary
    if (focusSection === "details") return focusIndex === 0 ? detailsButton : detailRows.itemAt(focusIndex - 1)
    return [contextButton, refreshButton, grafanaButton].concat(hasActivityGps ? [gpsButton] : [])
      .concat(latestActivityContext ? [activityGrafanaButton] : [])[focusIndex]
  }
  function revealCursor() {
    var item = cursorItem()
    if (coach.expanded || setup.expanded || !cursorActive || !item) return
    // Scrolling moves items under a stationary pointer; don't let that steal the cursor.
    revealGuard.restart()
    var top = item.mapToItem(content, 0, 0).y, bottom = top + item.height
    var y = scroll.contentY
    if (top < y || item.height > scroll.height) y = top
    else if (bottom > y + scroll.height) y = bottom - scroll.height
    scroll.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height), y))
  }
  function moveCursor(dx, dy) {
    if (!cursorActive) { setCursor("stats", 0, true); return }
    if (dy) {
      var index = focusIndex + dy
      if ((focusSection === "stats" || focusSection === "details" || focusSection === "activities") && index >= 0 && index < sectionCount(focusSection))
        setCursor(focusSection, index, true)
      else {
        var section = sections[Math.max(0, Math.min(sections.length - 1, sections.indexOf(focusSection) + dy))]
        if (section === focusSection) { revealCursor(); return }
        var next = section === "selector" ? historyFields.findIndex(function(field) { return field.key === root.historyKey })
          : dy < 0 && (section === "stats" || section === "details" || section === "activities") ? sectionCount(section) - 1 : 0
        setCursor(section, next, true)
      }
    } else if (dx) {
      if (focusSection === "selector" || focusSection === "footer") setCursor(focusSection, focusIndex + dx, true)
      else {
        if (focusSection === "history") historyChart.moveCursor(dx)
        else if (focusSection === "secondaryHistory") secondaryHistoryChart.moveCursor(dx)
        else if (focusSection === "stress") stressChart.moveCursor(dx)
        revealCursor()
      }
    }
  }
  function selectHistory(index, reveal) {
    historyKey = historyFields[index].key
    setCursor("history", 0, reveal)
  }
  function toggleDetails(reveal) {
    if (!activityDetails.length) return
    showDetails = !showDetails
    setCursor("details", showDetails ? 1 : 0, reveal)
  }
  function openContext() {
    if (!canOpenContext) return
    if (activityContext) service.openActivity(contextActivity.connectId)
    else service.openGrafana(grafanaContext)
  }
  function activateCursor() {
    if (!cursorActive) { setCursor("stats", 0, true); return }
    if (focusSection === "selector") selectHistory(focusIndex, true)
    else if (focusSection === "activities" && focusIndex === visibleActivities.length && moreActivities) showMoreActivities(true)
    else if (focusSection === "details" && focusIndex === 0) toggleDetails(true)
    else if (focusSection === "footer") {
      var button = cursorItem()
      if (button.enabled) button.clicked()
    } else openContext()
  }
  function textKey(text) {
    var key = text.toLowerCase(), index = "12345".indexOf(key)
    if (key === "s") setup.open()
    else if (key === "c") coach.open()
    else if (key.length === 1 && index >= 0) selectHistory(index, true)
    else if (key === "b") setCursor("stress", 0, true)
    else if (key === "w") setCursor("weekly", 0, true)
    else if (key === "d") toggleDetails(true)
    else if (key === "a") { setCursor("activity", 0, true); openContext() }
    else if (key === "o") openContext()
    else if (key === "g" && canOpenGrafana) service.openGrafana()
    else if (key === "r" && service && !busy) service.refresh(true)
  }
  onSectionsChanged: clampNavigation()
  onFooterCountChanged: clampNavigation()
  onVisibleActivitiesChanged: clampNavigation()
  onActivityDetailsChanged: clampNavigation()
  onShowDetailsChanged: clampNavigation()
  onOpenedChanged: {
    if (opened) {
      cursorActive = false
      activityLimit = 10
      focusSection = "stats"; focusIndex = 0; contextSection = "stats"; contextIndex = 0
      scroll.contentY = 0
      if (service) service.ensureCharts()
    } else { coach.dismiss(); setup.dismiss() }
  }
  onServiceChanged: if (opened && service) service.ensureCharts()
  function scrollCoach(direction, page) {
    scroll.contentY = Math.max(0, Math.min(Math.max(0, scroll.contentHeight - scroll.height),
      scroll.contentY + direction * (page ? scroll.height * 0.8 : Style.space(60))))
  }
  Timer { id: revealGuard; interval: 100 }

  Ui.KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem; bar: root.bar; owner: root.hostWidget || root
    open: root.opened; focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(500))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(740))
    Ui.PanelKeyCatcher {
      id: keys
      objectName: "garminPanelKeys"
      anchors.fill: parent
      blocked: coach.expanded || coach.activeFocus || setup.expanded || setup.activeFocus
      Keys.forwardTo: [scrollKeys]
      onCloseRequested: setup.expanded ? setup.dismiss() : coach.expanded ? coach.dismiss() : root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onTextKey: function(text) { root.textKey(text) }
      Flickable {
        id: scroll
        objectName: "garminPanelScroll"
        anchors.fill: parent; clip: true
        contentWidth: width; contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
        Column {
          id: content
          width: scroll.width; spacing: Style.spacing.panelGap
          Row {
            width: parent.width; spacing: Style.space(12)
            WatchFace {
              width: Math.max(0, parent.width - coachEntrySlot.width - parent.spacing)
              payload: root.payload
              modelOverride: root.setting("watchModel", "")
              demoMode: !!root.service && root.service.demoMode
              ink: Color.popups.text; accent: Color.popups.text; fontFamily: Style.font.family
              textSize: Math.max(12, Style.font.body); unit: Style.spaceReal(1)
            }
            Item {
              id: coachEntrySlot
              objectName: "coachHeaderSlot"
              width: Math.min(coach.entryButton.implicitWidth, parent.width * 0.45)
              height: coach.entryButton.implicitHeight
            }
          }
          Text {
            visible: text !== ""; width: parent.width; text: root.statusText
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
          }
          Setup {
            id: setup
            objectName: "garminPanelSetup"
            width: parent.width; service: root.service
            onOpenedGuide: { coach.dismiss(); scroll.contentY = 0 }
            onDismissed: keys.forceActiveFocus()
            onScrollRequested: function(direction, page) { root.scrollCoach(direction, page) }
            onFocusMoved: function(item) {
              var top = item.mapToItem(content, 0, 0).y
              if (top < scroll.contentY || item.height > scroll.height) scroll.contentY = top
              else if (top + item.height > scroll.contentY + scroll.height)
                scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, top + item.height - scroll.height))
            }
          }
          Text {
            width: parent.width; wrapMode: Text.Wrap
            text: "J/K: navigate / H/L: choose or inspect / Enter: activate\n1-5: history / B: overlay / W: weekly / O: open context / C: coach / S: setup"
            color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
          Coach {
            id: coach
            objectName: "garminPanelCoach"
            width: parent.width; service: root.service; stepGoal: root.stepGoal
            entryContainer: coachEntrySlot
            onExpandedChanged: if (expanded) setup.dismiss()
            onDismissed: keys.forceActiveFocus()
            onScrollRequested: function(direction, page) { root.scrollCoach(direction, page) }
            onFocusMoved: function(item) {
              var top = item.mapToItem(content, 0, 0).y
              if (top < scroll.contentY) scroll.contentY = top
              else if (top + item.height > scroll.contentY + scroll.height)
                scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, top + item.height - scroll.height))
            }
          }
          Column {
            width: parent.width; spacing: Style.space(10)
            Row {
              width: parent.width; spacing: Style.space(8)
              Text { width: (parent.width - parent.spacing * 2) * 0.42; text: "DAILY STATS"; elide: Text.ElideRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
              Text { width: (parent.width - parent.spacing * 2) * 0.27; text: root.currentDay ? "Today" : "Latest"; horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
              Text { width: (parent.width - parent.spacing * 2) * 0.31; text: "7d avg"; horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
            }
            Repeater {
              id: statRows
              model: root.fields
              Item {
                id: statRow
                required property var modelData
                required property int index
                readonly property var metric: root.metrics[modelData.key]
                readonly property bool supplemental: ["sleepDuration", "restingHeartRate", "trainingReadiness", "stress"].indexOf(modelData.key) >= 0
                readonly property bool stale: Model.stale(modelData.key, metric, root.now, supplemental ? root.payload.wellnessFetchedAt : root.payload.fetchedAt)
                readonly property bool oldDate: !!metric && (!root.currentDay || !root.payload.sourceDate || metric.date !== root.payload.sourceDate)
                readonly property var average: Model.average(root.dailyHistory[modelData.key] || [])
                width: parent.width; implicitHeight: statValues.implicitHeight
                Ui.CursorSurface { anchors.fill: parent; hasCursor: root.hasCursor("stats", statRow.index) }
                HoverHandler { onHoveredChanged: if (hovered) root.hoverCursor("stats", statRow.index) }
                TapHandler { onTapped: { root.setCursor("stats", statRow.index, false); root.openContext() } }
                Row {
                id: statValues
                width: parent.width; spacing: Style.space(8)
                Text { width: (parent.width - parent.spacing * 2) * 0.42; text: statRow.modelData.title; elide: Text.ElideRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
                Text {
                  width: (parent.width - parent.spacing * 2) * 0.27
                  text: (statRow.modelData.key === "steps" && statRow.stale ? "--" : root.metricText(statRow.modelData.key, statRow.metric ? statRow.metric.value : null))
                    + statRow.modelData.unit + ((statRow.stale || statRow.oldDate) && statRow.metric && statRow.metric.value !== null ? "*" : "")
                  horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.subtitle; font.bold: true
                  fontSizeMode: Text.HorizontalFit; minimumPixelSize: 9
                }
                Text {
                  width: (parent.width - parent.spacing * 2) * 0.31; text: root.metricText(statRow.modelData.key, statRow.average.value) + statRow.modelData.unit
                    + (statRow.average.count > 0 && (statRow.average.count < 7 || (statRow.supplemental ? root.supplementalCached : root.historyCached)) ? "*" : "")
                  fontSizeMode: Text.HorizontalFit; minimumPixelSize: 9
                  horizontalAlignment: Text.AlignRight; color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.subtitle
                }
                }
              }
            }
            Text {
              width: parent.width; wrapMode: Text.Wrap
              text: "7 completed days / battery peak / daily stress avg"
                + (root.fields.some(function(field) { var n = Model.average(root.dailyHistory[field.key] || []).count; return n > 0 && n < 7 }) ? " / * incomplete history" : "")
                + (root.historyCached || root.supplementalCached ? " / * cached history" : "")
                + (root.payload.historyError && !root.payload.historyFetchedAt ? " / history unavailable" : "")
              color: Color.popups.text; opacity: 0.55; font.family: Style.font.family; font.pixelSize: Math.max(11, Math.round(Style.font.body * 0.9))
            }
            Text {
              visible: text !== ""; width: parent.width; wrapMode: Text.Wrap
              text: {
                var notes = []
                for (var i = 0; i < root.fields.length; i++) {
                  var field = root.fields[i], metric = root.metrics[field.key]
                  var fetched = root.payload.wellness && root.payload.wellness[field.key] ? root.payload.wellnessFetchedAt : root.payload.fetchedAt
                  if (metric && metric.value !== null && (Model.stale(field.key, metric, root.now, fetched) || !root.currentDay || !root.payload.sourceDate || metric.date !== root.payload.sourceDate))
                    notes.push(field.title + " " + (metric.date || "unavailable"))
                }
                return notes.length ? "* Older samples: " + notes.join(" / ") : ""
              }
              color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Math.max(11, Math.round(Style.font.body * 0.9))
            }
          }
          Column {
            width: parent.width; spacing: Style.spacing.rowGap
            Flow {
              width: parent.width; spacing: Style.space(4)
              Repeater {
                id: selectors
                model: root.historyFields
                Ui.Button {
                  id: selector
                  required property var modelData
                  required property int index
                  text: modelData.historyTitle; selected: root.historyKey === modelData.key
                  hasCursor: root.hasCursor("selector", index)
                  fontSize: Style.font.bodySmall
                  tooltipText: "History: keys 1-5 / Enter selects / B overlay"
                  onHovered: function(hovered) { if (hovered) root.hoverCursor("selector", selector.index) }
                  onClicked: root.selectHistory(index, false)
                }
              }
            }
            Chart {
              id: historyChart
              width: parent.width; title: (root.historyKey === "sleep" ? "Sleep score / " : root.historyKey === "hrv" ? "HRV / " : "") + "Last 7 completed days" + ((root.supplementalSelected ? root.supplementalCached : root.historyCached) ? " / cached" : "")
              samples: root.dailyHistory[root.historyKey] || []
              ceiling: ["steps", "hrv"].indexOf(root.historyKey) >= 0 ? 0 : 100
              unit: root.historyKey === "steps" ? "steps" : root.historyKey === "hrv" ? "ms" : "score"
              selected: root.hasCursor("history", 0); ink: Color.popups.text
              onActivated: root.hoverCursor("history", 0)
            }
            Chart {
              id: secondaryHistoryChart
              visible: root.pairedHistory
              width: parent.width; title: (root.historyKey === "sleep" ? "Sleep hours" : "Resting HR") + " / Last 7 completed days" + (root.supplementalCached ? " / cached" : "")
              samples: root.historyKey === "sleep"
                ? (root.dailyHistory.sleepDuration || []).map(function(point) { return {date: point.date, value: typeof point.value === "number" ? point.value / 3600 : null} })
                : root.dailyHistory.restingHeartRate || []
              ceiling: 0; unit: root.historyKey === "sleep" ? "hours" : "bpm"
              selected: root.hasCursor("secondaryHistory", 0); ink: Color.popups.text
              onActivated: root.hoverCursor("secondaryHistory", 0)
            }
          }
          StressChart {
            id: stressChart
            width: parent.width
            batterySamples: root.payload.charts ? root.payload.charts.bodyBattery || [] : []
            stressSamples: root.payload.stressSeries || []
            endTime: Model.validTime(root.payload.sourceDayEnd) ? Math.min(root.now, Date.parse(root.payload.sourceDayEnd)) : root.now
            startTime: Model.validTime(root.payload.sourceDayStart) ? Date.parse(root.payload.sourceDayStart) : root.now - 86400000
            selected: root.hasCursor("stress", 0)
            onActivated: root.hoverCursor("stress", 0)
            notice: (!root.currentDay ? "Previous day" : "")
              + (root.payload.stressError ? (!root.currentDay ? " / " : "") + (root.payload.stressFetchedAt ? "Stress cached" : "Stress unavailable") : "")
            cached: root.cached
              || (!!root.payload.stressFetchedAt && root.now - Date.parse(root.payload.stressFetchedAt) > 3600000)
              || (!!root.payload.chartsFetchedAt && root.now - Date.parse(root.payload.chartsFetchedAt) > 3600000)
          }
          Rectangle { width: parent.width; height: 1; color: Color.popups.text; opacity: 0.15 }
          Column {
            width: parent.width; spacing: Style.space(10)
            Item {
              id: weeklySummary
              width: parent.width; implicitHeight: weeklyValues.implicitHeight
              Ui.CursorSurface { anchors.fill: parent; hasCursor: root.hasCursor("weekly", 0) }
              HoverHandler { onHoveredChanged: if (hovered) root.hoverCursor("weekly", 0) }
              TapHandler { onTapped: root.setCursor("weekly", 0, false) }
              Column {
                id: weeklyValues
                width: parent.width; spacing: Style.spacing.labelGap
                Text { text: "ACTIVITIES"; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
                Text {
                  width: parent.width; wrapMode: Text.Wrap; text: root.activitiesDateLabel
                  color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
                }
                Text {
                  objectName: "activitiesTotals"
                  width: parent.width; wrapMode: Text.Wrap
                  text: (root.activitiesOverview ? root.activitiesOverview.count : "--") + " recorded / "
                    + root.activityTotal(root.activitiesOverview ? root.activitiesOverview.duration : null, root.activitiesOverview ? root.activitiesOverview.count : 0, "h") + " / "
                    + root.activityTotal(root.activitiesOverview ? root.activitiesOverview.calories : null, root.activitiesOverview ? root.activitiesOverview.count : 0, "kcal")
                  color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.subtitle; font.bold: true
                }
                Text {
                  visible: text !== ""; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText
                  text: root.activitiesStatus
                  color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
                }
              }
            }
            Repeater {
              model: root.activitiesOverview ? root.activitiesOverview.types : []
              Text {
                required property var modelData
                objectName: "activityTypeTotal"
                width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText
                text: modelData.type + ": " + modelData.count + " recorded / "
                  + root.activityTotal(modelData.duration, modelData.count, "h") + " / "
                  + root.activityTotal(modelData.distance, modelData.count, "km")
                color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
              }
            }
            Text {
              visible: !!root.activitiesOverview && root.activitiesOverview.count > 0
              width: parent.width; wrapMode: Text.Wrap
              text: "Recorded totals only / -- unknown / known counts mark partial totals\nNewest first / showing " + root.visibleActivities.length + " of " + (root.activitiesOverview ? root.activitiesOverview.count : 0)
              color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
            }
            Repeater {
              id: activityRows
              model: root.visibleActivities
              Item {
                id: recordedActivity
                required property var modelData
                required property int index
                readonly property string description: modelData.date + " / " + Model.activityName(modelData.type)
                readonly property string values: Model.duration(modelData.durationSeconds)
                  + (Model.numeric(modelData.distanceMeters) !== "--" ? " / " + root.activityTotal({value: modelData.distanceMeters, knownCount: 1}, 1, "km") : "")
                  + (Model.numeric(modelData.calories) !== "--" ? " / " + Model.numeric(modelData.calories) + " kcal" : "")
                width: parent.width; implicitHeight: recordedValues.implicitHeight + Style.space(8)
                Accessible.role: Accessible.Button
                Accessible.name: description + " / " + values
                Accessible.description: root.canOpenActivity(modelData) ? "Open activity in Garmin Connect" : "Garmin Connect link unavailable"
                Ui.CursorSurface { anchors.fill: parent; hasCursor: root.hasCursor("activities", recordedActivity.index) }
                MouseArea {
                  anchors.fill: parent; hoverEnabled: true
                  onEntered: root.hoverCursor("activities", recordedActivity.index)
                  onPositionChanged: root.hoverCursor("activities", recordedActivity.index)
                  onClicked: { root.setCursor("activities", recordedActivity.index, false); root.openContext() }
                }
                ActivityIcon {
                  x: Style.space(4); y: Style.space(4); width: Style.space(24); height: width
                  kind: Model.activityIconKind(recordedActivity.modelData.type); ink: Color.popups.text; Accessible.ignored: true
                }
                Column {
                  id: recordedValues
                  x: Style.space(36); y: Style.space(4); width: Math.max(0, parent.width - x); spacing: Style.spacing.labelGap
                  Text {
                    width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText; text: recordedActivity.description
                    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
                  }
                  Text {
                    width: parent.width; wrapMode: Text.Wrap; text: recordedActivity.values
                    color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
                  }
                }
              }
            }
            Ui.Button {
              id: moreActivitiesButton
              visible: root.moreActivities
              text: "Show more (" + Math.min(10, root.activities ? root.activities.items.length - root.visibleActivities.length : 0) + ")"
              hasCursor: root.hasCursor("activities", root.visibleActivities.length)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("activities", root.visibleActivities.length) }
              onClicked: root.showMoreActivities(true)
            }
          }
          Rectangle { width: parent.width; height: 1; color: Color.popups.text; opacity: 0.15 }
          Column {
            width: parent.width; spacing: Style.space(10)
            Text { text: "LATEST ACTIVITY"; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
            Item {
              id: activitySummary
              width: parent.width; implicitHeight: activityRow.implicitHeight
              Ui.CursorSurface { anchors.fill: parent; hasCursor: root.hasCursor("activity", 0) }
              // Child controls own their hover; the summary only claims pointer movement outside them.
              MouseArea {
                anchors.fill: parent; hoverEnabled: true
                onEntered: root.hoverCursor("activity", 0)
                onPositionChanged: root.hoverCursor("activity", 0)
                onClicked: { root.setCursor("activity", 0, false); root.openContext() }
              }
              Row {
              id: activityRow
              width: parent.width; spacing: Style.space(16)
              ActivityIcon {
                width: Style.space(28); height: width
                kind: Model.activityIconKind(root.activity ? root.activity.type : "")
                ink: Color.popups.text; Accessible.ignored: true
              }
              Column {
                width: Math.max(0, parent.width - Style.space(44)); spacing: Style.spacing.labelGap
                Text {
                  width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText
                  text: root.activity ? Model.activityName(root.activity.type) : root.payload.activityError ? "Activity unavailable" : root.payload.activityFetchedAt ? "No activity in the last year" : "Waiting for activity"
                  color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.subtitle; font.bold: true
                }
                Text {
                  visible: !!root.activity; width: parent.width; wrapMode: Text.Wrap
                  text: root.activity ? root.stamp(root.activity.time) + (root.activityCached ? " / cached" : "") : ""
                  color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.body
                }
                Text {
                  visible: !!root.activity; width: parent.width; wrapMode: Text.Wrap
                  text: root.activity ? Model.duration(root.activity.durationSeconds) + (Model.activityDistance(root.activity) ? " / " + Model.activityDistance(root.activity) : "") : ""
                  color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
                }
                Text {
                  visible: text !== ""; width: parent.width; wrapMode: Text.Wrap
                  text: Model.activityPerformance(root.activity)
                    + (root.activity && root.activity.averageHR > 0 ? (Model.activityPerformance(root.activity) ? " / " : "") + Model.numeric(root.activity.averageHR) + " bpm avg" : "")
                  color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
                }
                Text {
                  visible: !!root.activity; width: parent.width; wrapMode: Text.Wrap
                  text: root.activity ? (root.activity.calories !== null ? Model.numeric(root.activity.calories) + " kcal" : "")
                    + (root.activity.bmrCalories !== null ? (root.activity.calories !== null ? " / " : "") + Model.numeric(root.activity.bmrCalories) + " resting (BMR)" : "") : ""
                  color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
                }
                Ui.Button {
                  id: detailsButton
                  visible: root.activityDetails.length > 0
                  text: root.showDetails ? "Less (D)" : "Details (D)"; selected: root.showDetails
                  hasCursor: root.hasCursor("details", 0)
                  onHovered: function(hovered) { if (hovered) root.hoverCursor("details", 0) }
                  tooltipText: "Activity details (D)"; onClicked: root.toggleDetails(false)
                }
                Column {
                  visible: root.showDetails; width: parent.width; spacing: Style.spacing.labelGap
                  Repeater {
                    id: detailRows
                    model: root.activityDetails
                    Item {
                      id: detailRow
                      required property var modelData
                      required property int index
                      width: parent.width; implicitHeight: detailValues.implicitHeight
                      Ui.CursorSurface { anchors.fill: parent; hasCursor: root.hasCursor("details", detailRow.index + 1) }
                      MouseArea {
                        anchors.fill: parent; hoverEnabled: true
                        onEntered: root.hoverCursor("details", detailRow.index + 1)
                        onPositionChanged: root.hoverCursor("details", detailRow.index + 1)
                        onClicked: { root.setCursor("details", detailRow.index + 1, false); root.openContext() }
                      }
                      Row {
                      id: detailValues
                      width: parent.width; spacing: Style.spacing.rowGap
                      Text { width: (parent.width - parent.spacing) * 0.55; text: detailRow.modelData.label; wrapMode: Text.Wrap; color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.body }
                      Text { width: (parent.width - parent.spacing) * 0.45; text: detailRow.modelData.value; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
                      }
                    }
                  }
                }
              }
              }
            }
          }
          Flow {
            width: parent.width; spacing: Style.space(8)
            Ui.Button {
              id: contextButton
              enabled: root.canOpenContext
              width: Math.min(parent.width, contextText.implicitWidth + horizontalPadding * 2)
              implicitHeight: contextText.height + verticalPadding * 2
              tooltipText: contextText.text
              Accessible.role: Accessible.Button
              Accessible.name: contextText.text
              hasCursor: root.hasCursor("footer", 0)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("footer", 0) }
              onClicked: root.openContext()
              Text {
                id: contextText
                anchors.centerIn: parent
                width: Math.max(0, parent.width - contextButton.horizontalPadding * 2)
                text: root.activityContext ? "Open activity in Garmin Connect (O)" : "Open " + root.contextLabel + " in Grafana (O)"; wrapMode: Text.Wrap
                color: contextButton.foreground; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
              }
            }
            Ui.Button {
              id: refreshButton
              text: root.busy ? "Refreshing..." : "Refresh"; enabled: !!root.service && !root.busy
              hasCursor: root.hasCursor("footer", 1)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("footer", 1) }
              tooltipText: "Refresh (R)"; onClicked: root.service.refresh(true)
            }
            Ui.Button {
              id: grafanaButton
              text: "Grafana (G)"; enabled: root.canOpenGrafana
              hasCursor: root.hasCursor("footer", 2)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("footer", 2) }
              tooltipText: "Open Grafana (G)"; onClicked: root.service.openGrafana()
            }
            Ui.Button {
              id: gpsButton
              visible: root.hasActivityGps; enabled: root.canOpenGrafana
              text: "Activity GPS"
              tooltipText: "Open the verified activity GPS selector in Grafana"
              hasCursor: root.hasCursor("footer", 3)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("footer", 3) }
              onClicked: root.service.openGrafana({key: "activityGps"})
            }
            Ui.Button {
              id: activityGrafanaButton
              visible: root.latestActivityContext; enabled: root.canOpenGrafana
              text: "Activity in Grafana"
              tooltipText: "Open the activity dashboard in Grafana"
              hasCursor: root.hasCursor("footer", root.hasActivityGps ? 4 : 3)
              onHovered: function(hovered) { if (hovered) root.hoverCursor("footer", root.hasActivityGps ? 4 : 3) }
              onClicked: root.service.openGrafana({key: "activity"})
            }
          }
          Text {
            width: parent.width; wrapMode: Text.Wrap
            text: "Up/Down, J/K: navigate / Left/Right, H/L: choose or inspect\nEnter/Space: activate / 1-5: history / B: overlay / D: details\nW: weekly / A: latest in Connect / O: context / G: Grafana\nC: coach / S: setup / R: refresh / Tab/Shift-Tab: panels / Esc: close"
            color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.bodySmall
          }
        }
      }
      Item {
        id: scrollKeys
        // Consent can outlive focus on a button; never route its scroll keys through section navigation.
        Keys.onPressed: function(event) {
          if (!keys.blocked) return
           if (event.key === Qt.Key_Escape) { setup.expanded ? setup.dismiss() : coach.dismiss(); event.accepted = true; return }
          var direction = event.key === Qt.Key_Down || event.key === Qt.Key_PageDown ? 1
            : event.key === Qt.Key_Up || event.key === Qt.Key_PageUp ? -1 : 0
          if (!direction) return
          root.scrollCoach(direction, event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp)
          event.accepted = true
        }
      }
    }
  }
}
