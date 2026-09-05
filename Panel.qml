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
  property bool showDetails: false
  property string activeChart: "history"
  property string historyKey: "steps"
  readonly property var fields: [
    {key: "steps", title: "Steps", historyTitle: "Steps", unit: ""},
    {key: "bodyBattery", title: "Body battery", historyTitle: "Battery peak", unit: ""},
    {key: "sleep", title: "Sleep score", historyTitle: "Sleep score", unit: ""},
    {key: "sleepDuration", title: "Sleep time", historyTitle: "Sleep time", unit: ""},
    {key: "hrv", title: "HRV (ms)", historyTitle: "HRV", unit: ""},
    {key: "restingHeartRate", title: "Resting HR (bpm)", historyTitle: "Resting HR", unit: ""},
    {key: "stress", title: "Stress", historyTitle: "Stress", unit: ""}
  ]
  readonly property var payload: service && service.payload && service.payload.schemaVersion === 1 ? service.payload : ({})
  readonly property var metrics: Object.assign({}, payload.metrics || {}, payload.wellness || {})
  readonly property var dailyHistory: Object.assign({}, payload.history || {}, payload.supplementalHistory || {})
  readonly property bool supplementalSelected: ["sleepDuration", "restingHeartRate", "trainingReadiness", "stress"].indexOf(historyKey) >= 0
  readonly property var activity: payload.latestActivity || null
  readonly property bool busy: !!service && service.busy
  readonly property real now: service ? service.now : Date.now()
  readonly property bool cached: payload.status === "cached" || (!!payload.fetchedAt && now - Date.parse(payload.fetchedAt) > 3600000)
  readonly property bool historyCached: cached || !!payload.historyError || (!!payload.historyFetchedAt && now - Date.parse(payload.historyFetchedAt) > 3600000)
  readonly property bool activityCached: cached || !!payload.activityError || (!!payload.activityFetchedAt && now - Date.parse(payload.activityFetchedAt) > 3600000)
  readonly property bool supplementalCached: cached || !!payload.supplementalHistoryError || (!!payload.supplementalHistoryFetchedAt && now - Date.parse(payload.supplementalHistoryFetchedAt) > 3600000)
  readonly property var activityDetails: Model.activityDetails(activity)
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
  function switchPanel(direction) {
    return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(hostWidget || root, direction) : false
  }
  onOpenedChanged: if (opened && service) service.ensureCharts()
  onServiceChanged: if (opened && service) service.ensureCharts()

  Ui.KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem; bar: root.bar; owner: root.hostWidget || root
    open: root.opened; focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(500))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(740))
    Ui.PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (dx) {
          if (root.activeChart === "stress") stressChart.moveCursor(dx)
          else historyChart.moveCursor(dx)
        }
        if (dy) scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, scroll.contentY + dy * Style.space(60)))
      }
      onTextKey: function(text) {
        var key = text.toLowerCase()
        if (key === "r" && root.service && !root.busy) root.service.refresh(true)
        if (key === "g" && root.service) root.service.openGrafana()
        if (key === "b") root.activeChart = root.activeChart === "stress" ? "history" : "stress"
        var index = "1234567".indexOf(key)
        if (index >= 0 && key.length === 1) { root.historyKey = root.fields[index].key; root.activeChart = "history" }
      }
      Flickable {
        id: scroll
        anchors.fill: parent; clip: true
        contentWidth: width; contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
        Column {
          id: content
          width: scroll.width; spacing: Style.spacing.panelGap
          WatchFace {
            width: parent.width; payload: root.payload
            modelOverride: root.setting("watchModel", "")
            demoMode: !!root.service && root.service.demoMode
            ink: Color.popups.text; accent: Color.popups.text; fontFamily: Style.font.family
            textSize: Math.max(12, Style.font.body); unit: Style.spaceReal(1)
          }
          Text {
            visible: text !== ""; width: parent.width; text: root.statusText
            textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body
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
              model: root.fields
              Row {
                id: statRow
                required property var modelData
                readonly property var metric: root.metrics[modelData.key]
                readonly property bool supplemental: ["sleepDuration", "restingHeartRate", "trainingReadiness", "stress"].indexOf(modelData.key) >= 0
                readonly property bool stale: Model.stale(modelData.key, metric, root.now, supplemental ? root.payload.wellnessFetchedAt : root.payload.fetchedAt)
                readonly property bool oldDate: !!metric && (!root.currentDay || !root.payload.sourceDate || metric.date !== root.payload.sourceDate)
                readonly property var average: Model.average(root.dailyHistory[modelData.key] || [])
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
                model: root.fields
                Ui.Button {
                  required property var modelData
                  text: modelData.historyTitle; selected: root.historyKey === modelData.key
                  fontSize: Style.font.bodySmall
                  tooltipText: "History: keys 1-7 / B switch chart"
                  onClicked: { root.historyKey = modelData.key; root.activeChart = "history"; keys.forceActiveFocus() }
                }
              }
            }
            Chart {
              id: historyChart
              width: parent.width; title: "Last 7 completed days" + ((root.supplementalSelected ? root.supplementalCached : root.historyCached) ? " / cached" : "")
              samples: (root.dailyHistory[root.historyKey] || []).map(function(point) { return {date: point.date, value: point.value === null ? null : root.historyKey === "sleepDuration" ? point.value / 3600 : point.value} })
              ceiling: ["steps", "hrv", "restingHeartRate", "sleepDuration"].indexOf(root.historyKey) >= 0 ? 0 : 100
              unit: root.historyKey === "steps" ? "steps" : root.historyKey === "hrv" ? "ms" : root.historyKey === "sleepDuration" ? "hours" : root.historyKey === "restingHeartRate" ? "bpm" : "score"
              selected: root.activeChart === "history"; ink: Color.popups.text
              onActivated: root.activeChart = "history"
            }
          }
          StressChart {
            id: stressChart
            width: parent.width
            batterySamples: root.payload.charts ? root.payload.charts.bodyBattery || [] : []
            stressSamples: root.payload.stressSeries || []
            endTime: Model.validTime(root.payload.sourceDayEnd) ? Math.min(root.now, Date.parse(root.payload.sourceDayEnd)) : root.now
            startTime: Model.validTime(root.payload.sourceDayStart) ? Date.parse(root.payload.sourceDayStart) : root.now - 86400000
            selected: root.activeChart === "stress"
            onActivated: { root.activeChart = "stress"; keys.forceActiveFocus() }
            notice: (!root.currentDay ? "Previous day" : "")
              + (root.payload.stressError ? (!root.currentDay ? " / " : "") + (root.payload.stressFetchedAt ? "Stress cached" : "Stress unavailable") : "")
            cached: root.cached
              || (!!root.payload.stressFetchedAt && root.now - Date.parse(root.payload.stressFetchedAt) > 3600000)
              || (!!root.payload.chartsFetchedAt && root.now - Date.parse(root.payload.chartsFetchedAt) > 3600000)
          }
          Rectangle { width: parent.width; height: 1; color: Color.popups.text; opacity: 0.15 }
          Column {
            width: parent.width; spacing: Style.space(10)
            Text { text: "LATEST ACTIVITY"; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true }
            Row {
              width: parent.width; spacing: Style.space(16)
              ActivityIcon {
                width: Style.space(28); height: width
                kind: Model.activityKind(root.activity ? root.activity.type : "")
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
                  visible: root.activityDetails.length > 0
                  text: root.showDetails ? "Less" : "Details"; selected: root.showDetails
                  tooltipText: "Activity details"; onClicked: root.showDetails = !root.showDetails
                }
                Column {
                  visible: root.showDetails; width: parent.width; spacing: Style.spacing.labelGap
                  Repeater {
                    model: root.activityDetails
                    Row {
                      required property var modelData
                      width: parent.width; spacing: Style.spacing.rowGap
                      Text { width: (parent.width - parent.spacing) * 0.55; text: parent.modelData.label; wrapMode: Text.Wrap; color: Color.popups.text; opacity: 0.65; font.family: Style.font.family; font.pixelSize: Style.font.body }
                      Text { width: (parent.width - parent.spacing) * 0.45; text: parent.modelData.value; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Style.font.body }
                    }
                  }
                }
              }
            }
          }
          Flow {
            width: parent.width; spacing: Style.space(8)
            Ui.Button {
              text: root.busy ? "Refreshing..." : "Refresh"; enabled: !!root.service && !root.busy
              tooltipText: "Refresh (R)"; onClicked: root.service.refresh(true)
            }
            Ui.Button { text: "Grafana"; enabled: !!root.service; tooltipText: "Open Grafana (G)"; onClicked: root.service.openGrafana() }
          }
        }
      }
    }
  }
}
