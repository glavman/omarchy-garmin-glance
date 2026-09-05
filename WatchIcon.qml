import QtQuick

Item {
  id: root
  property color ink: "white"
  property string watchStyle: "generic"
  readonly property bool square: watchStyle === "square" || watchStyle === "slim"
  Rectangle {
    anchors.horizontalCenter: parent.horizontalCenter
    y: parent.height * 0.02
    width: parent.width * 0.34; height: parent.height * 0.96
    color: "transparent"
    Rectangle { width: parent.width; height: root.height * 0.16; radius: 1; color: root.ink }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: root.height * 0.16; radius: 1; color: root.ink }
  }
  Rectangle {
    id: dial
    anchors.centerIn: parent
    width: parent.width * 0.72; height: parent.height * 0.65
    radius: root.square ? width * 0.2 : width / 2
    color: "transparent"; border.color: root.ink
    border.width: Math.max(1, root.width * (root.watchStyle === "rugged" ? 0.1 : 0.065))
  }
  Rectangle {
    x: root.width * 0.48; y: root.height * 0.37
    width: Math.max(1, root.width * 0.06); height: root.height * 0.16; color: root.ink
  }
  Rectangle {
    x: root.width * 0.48; y: root.height * 0.5
    width: root.width * 0.16; height: Math.max(1, root.height * 0.06); color: root.ink
  }
  Rectangle {
    x: root.width * 0.87; y: root.height * 0.41
    width: root.width * 0.09; height: root.height * 0.16; radius: 1; color: root.ink
  }
}
