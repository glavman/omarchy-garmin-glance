pragma ComponentBehavior: Bound
import QtQuick
import qs.Commons
import qs.Ui as Ui

FocusScope {
  id: root
  property var service: null
  property real stepGoal: 10000
  property Item entryContainer: null
  readonly property alias entryButton: entry
  property bool expanded: false
  property string intent: ""
  property int days: 7
  property bool confirmingClear: false
  readonly property bool live: !!service && !service.demoMode && service.actionsBlocked !== true
  readonly property bool busy: !!service && service.coachBusy
  readonly property string agent: service ? service.coachAgent : ""
  readonly property bool canOpen: expanded && live && !busy && !confirmingClear && ["day", "week", "question"].indexOf(intent) >= 0
    && ["opencode", "claude", "codex", "grok"].indexOf(agent) >= 0
  signal dismissed()
  signal focusMoved(var item)
  signal scrollRequested(int direction, bool page)
  implicitHeight: content.implicitHeight

  function open() {
    if (!live || busy) return
    expanded = true
    intent = ""
    days = 7
    confirmingClear = false
    service.checkCoach()
    dayButton.forceActiveFocus()
  }
  function dismiss() {
    expanded = false
    intent = ""
    confirmingClear = false
    entry.forceActiveFocus()
    dismissed()
  }
  function chooseIntent(value) {
    if (!live || busy || confirmingClear || ["day", "week", "question"].indexOf(value) < 0) return
    intent = value
  }
  function launch() {
    if (canOpen) service.launchCoach(intent, days, stepGoal, agent)
  }
  function clearFiles() {
    if (!live || busy || !confirmingClear) return
    confirmingClear = false
    service.clearCoach()
  }
  onLiveChanged: if (!live) dismiss()
  Keys.onEscapePressed: function(event) { dismiss(); event.accepted = true }
  Keys.onPressed: function(event) {
    if (!expanded) return
    var direction = event.key === Qt.Key_Down || event.key === Qt.Key_PageDown ? 1
      : event.key === Qt.Key_Up || event.key === Qt.Key_PageUp ? -1 : 0
    if (!direction) return
    scrollRequested(direction, event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp)
    event.accepted = true
  }

  component CoachText: Text {
    width: parent.width
    textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(13, Style.font.body)
    Accessible.role: Accessible.StaticText; Accessible.name: text
  }
  component CoachButton: Ui.Button {
    id: button
    property string label: ""
    // Ui.Button's built-in label is single-line; retain its native surface with a wrapping label.
    width: Math.min(implicitWidth, parent.width)
    implicitWidth: caption.implicitWidth + horizontalPadding * 2 + Style.space(4)
    implicitHeight: caption.implicitHeight + verticalPadding * 2 + Style.space(4)
    bordered: true; focusable: true
    foreground: Color.popups.text; fontSize: Math.max(13, Style.font.body)
    opacity: enabled ? 1 : 0.5
    Accessible.role: Accessible.Button; Accessible.name: label
    Accessible.onPressAction: if (enabled) clicked()
    onActiveFocusChanged: if (activeFocus) root.focusMoved(button)
    Text {
      id: caption
      anchors.centerIn: parent
      width: Math.max(1, parent.width - button.horizontalPadding * 2 - Style.space(4))
      text: button.label; textFormat: Text.PlainText; wrapMode: Text.Wrap
      horizontalAlignment: Text.AlignHCenter
      color: button.selected ? button._selectedColor : button.foreground
      font.family: button.fontFamily; font.pixelSize: button.fontSize; font.bold: button.selected
    }
  }

  Column {
    id: content
    width: parent.width; spacing: Style.space(10)
    CoachButton {
      id: entry
      parent: root.entryContainer || content
      objectName: "coachEntry"
      label: root.expanded ? "Close coach" : "Ask Coach"
      enabled: root.live && (!root.busy || root.expanded)
      onClicked: root.expanded ? root.dismiss() : root.open()
    }
    CoachText {
      visible: !root.live
      text: root.service && root.service.demoMode ? "Coach is disabled in demo mode. No live coaching requests are made." : "Coach service unavailable."
    }
    Column {
      width: parent.width; spacing: Style.space(10); visible: root.expanded && root.live
      CoachText { text: "Choose an intent, then review what you will share." }
      Flow {
        width: parent.width; spacing: Style.space(8)
        enabled: !root.busy && !root.confirmingClear
        CoachButton {
          id: dayButton
          objectName: "coachDay"
          label: "Plan my day"; selected: root.intent === "day"
          onClicked: root.chooseIntent("day")
        }
        CoachButton {
          label: "Review my week"; selected: root.intent === "week"
          onClicked: root.chooseIntent("week")
        }
        CoachButton {
          label: "Ask a question"; selected: root.intent === "question"
          onClicked: root.chooseIntent("question")
        }
      }
      CoachText {
        objectName: "coachAgent"
        text: "Detected default agent: " + ({opencode: "OpenCode", claude: "Claude", codex: "Codex", grok: "Grok"}[root.agent] || "not confirmed")
          + ". Discovery is local only; it does not contact a provider."
      }
      CoachButton {
        label: "Check agent again"; enabled: !root.busy && !root.confirmingClear
        onClicked: root.service.checkCoach()
      }
      Column {
        width: parent.width; spacing: Style.space(10)
        visible: root.intent !== "" && !root.confirmingClear
        CoachText {
          text: root.intent === "day" ? "Consent / Plan my day" : root.intent === "week" ? "Consent / Review my week" : "Consent / Ask a question in the agent terminal"
          font.bold: true
        }
        CoachText { text: "History window" }
        Flow {
          width: parent.width; spacing: Style.space(8); enabled: !root.busy
          Repeater {
            model: [7, 30, 90]
            CoachButton {
              required property int modelData
              objectName: "coachDays_" + modelData
              label: modelData + " days"; selected: root.days === modelData
              Accessible.role: Accessible.RadioButton
              Accessible.checkable: true; Accessible.checked: selected
              onClicked: root.days = modelData
            }
          }
        }
        CoachText {
          text: "Shares all supported wellbeing metrics and recorded activity details within the chosen window, plus your step goal ("
            + root.stepGoal.toLocaleString(Qt.locale(), 'f', 0) + "). Unavailable data is marked."
        }
        CoachText {
          text: "Your existing agent may send this data to its provider and retain chat history. Its existing filesystem and tool permissions remain active; it is not sandboxed."
        }
        CoachText {
          text: "Plugin sessions expire after 24 hours, not agent or provider copies. Global agent configuration is unchanged."
        }
        CoachText {
          text: root.intent === "question" ? "Ask your question inside the agent terminal. This panel does not collect a question or generate an answer."
            : "Review the agent's response in its terminal. Coaching is not medical advice."
        }
        Flow {
          width: parent.width; spacing: Style.space(8)
          CoachButton {
            objectName: "coachLaunch"
            label: "Open agent"; enabled: root.canOpen
            onClicked: root.launch()
          }
          CoachButton {
            label: "Cancel consent"; enabled: !root.busy
            onClicked: { root.intent = ""; dayButton.forceActiveFocus() }
          }
        }
      }
      CoachText {
        objectName: "coachStatus"
        text: root.service ? root.service.coachMessage : ""
        visible: text !== ""
      }
      CoachButton {
        objectName: "coachClear"
        label: "Clear coaching files"; enabled: !root.busy; visible: !root.confirmingClear
        onClicked: { root.confirmingClear = true; clearConfirmation.forceActiveFocus() }
      }
      Column {
        width: parent.width; spacing: Style.space(8); visible: root.confirmingClear
        CoachText {
          text: "Clear all plugin-owned coaching sessions? Existing coaching sessions will stop working. This removes only this plugin's coaching files, not agent chat history or provider copies."
        }
        CoachButton {
          id: clearConfirmation
          objectName: "coachConfirmClear"
          label: "Confirm clear coaching files"; enabled: !root.busy
          onClicked: root.clearFiles()
        }
        CoachButton {
          label: "Cancel clear"; enabled: !root.busy
          onClicked: { root.confirmingClear = false; dayButton.forceActiveFocus() }
        }
      }
      CoachText { text: "Up / Down and Page Up / Page Down scroll. Tab / Shift-Tab moves between coach controls. Enter or Space activates. Escape closes coach."; opacity: 0.8 }
    }
  }
}
