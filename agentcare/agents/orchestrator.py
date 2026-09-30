
"""
AgentCare AI - Orchestrator Agent

Coordinates the complete AgentCare operational monitoring pipeline.

Historical mode:
    Simulation Agent only.
    Run ONCE to create the historical baseline.

Live monitoring mode:
    Simulation
        -> Data Cleaning
        -> Analysis
        -> Alert Detection
        -> Recommendation

The Orchestrator does not perform business calculations.
It delegates work to individual agents and stops the pipeline
when an upstream agent fails.
"""

from datetime import timedelta

from agentcare.agents.base import utcnow
from agentcare.agents.simulation_agent import SimulationAgent
from agentcare.agents.cleaning_agent import DataCleaningAgent
from agentcare.agents.analysis_agent import AnalysisAgent
from agentcare.agents.alert_detection_agent import AlertDetectionAgent
from agentcare.agents.recommendation_agent import RecommendationAgent
from agentcare.models import WorkflowExecutionLog


class OrchestratorAgent:

    name = "OrchestratorAgent"

    def __init__(self, session):
        self.session = session

    # ============================================================
    # WORKFLOW LOGGING
    # ============================================================

    def _log_start(
        self,
        workflow_name: str,
        agent_name: str,
        start_time,
    ):
        log = WorkflowExecutionLog(
            workflow_name=workflow_name,
            agent_name=agent_name,
            start_time=start_time,
            status="RUNNING",
        )

        self.session.add(log)
        self.session.commit()

        return log

    def _log_finish(
        self,
        log,
        status: str,
        error_info: str = None,
    ):
        log.status = status
        log.end_time = utcnow()
        log.error_info = error_info

        self.session.commit()

    # ============================================================
    # RUN ONE AGENT
    # ============================================================

    def _run_agent(
    self,
    workflow_name,
    agent_name,
    agent,
    start_time,
    run_kwargs=None,
):
        """
        Execute one agent and record its workflow status.
        """

        log = self._log_start(
            workflow_name,
            agent_name,
            start_time,
        )

        try:

            result = agent.run(**(run_kwargs or {}))

            if result.get("status") == "SUCCESS":

                self._log_finish(
                    log,
                    "COMPLETED",
                )

                return result

            error = result.get(
                "error",
                f"{agent_name} failed",
            )

            self._log_finish(
                log,
                "FAILED",
                error_info=error,
            )

            return result

        except Exception as exc:

            self.session.rollback()

            # Start a fresh transaction for workflow logging
            try:
                self._log_finish(
                    log,
                    "FAILED",
                    error_info=str(exc),
                )
            except Exception:
                self.session.rollback()

            return {
                "status": "FAILED",
                "error": str(exc),
            }

    # ============================================================
    # HISTORICAL SIMULATION
    # ============================================================

    def trigger_historical_simulation(
        self,
        start_time,
        days: int = 30,
    ):
        """
        Run historical simulation.

        IMPORTANT:
        This should normally be executed ONCE to create the
        historical baseline.

        It does NOT run cleaning, analysis, alert detection,
        or recommendation.
        """

        end_time = (
            start_time
            + timedelta(days=days)
        )

        log = self._log_start(
            "HISTORICAL_SIM",
            SimulationAgent.name,
            start_time,
        )

        try:

            agent = SimulationAgent(
                self.session
            )

            result = agent.run({
                "mode": "HISTORICAL",
                "start_time": start_time,
                "end_time": end_time,
            })

            if result["status"] == "SUCCESS":

                self._log_finish(
                    log,
                    "COMPLETED",
                )

            else:

                self._log_finish(
                    log,
                    "FAILED",
                    error_info=result.get("error"),
                )

            return result

        except Exception as exc:

            self.session.rollback()

            try:
                self._log_finish(
                    log,
                    "FAILED",
                    error_info=str(exc),
                )
            except Exception:
                self.session.rollback()

            return {
                "status": "FAILED",
                "error": str(exc),
            }

    # ============================================================
    # LIVE MONITORING PIPELINE
    # ============================================================

    def trigger_monitoring_cycle(
        self,
        window_start,
        window_end,
    ):
        """
        Run one live monitoring window.

        Pipeline:

            1. Simulation
            2. Data Cleaning
            3. Analysis
            4. Alert Detection
            5. Recommendation

        Every downstream agent runs only when the previous
        agent succeeds.
        """

        print("\n")
        print("=" * 70)
        print("AGENTCARE MONITORING CYCLE")
        print("=" * 70)

        print(
            f"\nWindow:"
            f"\n  {window_start}"
            f"\n  -> {window_end}"
        )

        # ========================================================
        # 1. SIMULATION
        # ========================================================

        print("\n[1/5] SIMULATION AGENT")

        simulation_log = self._log_start(
            "MONITORING",
            SimulationAgent.name,
            window_start,
        )

        try:

            simulation_agent = SimulationAgent(
                self.session
            )

            simulation_result = simulation_agent.run({
                "mode": "LIVE",
                "start_time": window_start,
                "end_time": window_end,
            })

            if simulation_result["status"] != "SUCCESS":

                self._log_finish(
                    simulation_log,
                    "FAILED",
                    error_info=simulation_result.get(
                        "error"
                    ),
                )

                return {
                    "status": "FAILED",
                    "failed_agent":
                        SimulationAgent.name,
                    "error":
                        simulation_result.get("error"),
                }

            self._log_finish(
                simulation_log,
                "COMPLETED",
            )

            print("✅ Simulation completed.")

        except Exception as exc:

            self.session.rollback()

            try:
                self._log_finish(
                    simulation_log,
                    "FAILED",
                    error_info=str(exc),
                )
            except Exception:
                self.session.rollback()

            return {
                "status": "FAILED",
                "failed_agent":
                    SimulationAgent.name,
                "error":
                    str(exc),
            }

        # ========================================================
        # 2. DATA CLEANING
        # ========================================================

        print("\n[2/5] DATA CLEANING AGENT")

        cleaning_result = self._run_agent(
            workflow_name="MONITORING",
            agent_name=DataCleaningAgent.__name__,
            agent=DataCleaningAgent(
                self.session
            ),
            start_time=window_start,
        )

        if cleaning_result["status"] != "SUCCESS":

            print(
                "\n❌ Pipeline stopped:"
                " Data Cleaning failed."
            )

            return {
                "status": "FAILED",
                "failed_agent":
                    DataCleaningAgent.__name__,
                "error":
                    cleaning_result.get("error"),
                "simulation":
                    simulation_result,
                "cleaning":
                    cleaning_result,
            }

        print("✅ Data Cleaning completed.")

        # ========================================================
        # 3. ANALYSIS
        # ========================================================

        print("\n[3/5] ANALYSIS AGENT")

        analysis_result = self._run_agent(
    workflow_name="MONITORING",
    agent_name=AnalysisAgent.__name__,
    agent=AnalysisAgent(
        self.session
    ),
    start_time=window_start,
    run_kwargs={
        "period_start": window_start,
        "period_end": window_end,
    },)

        if analysis_result["status"] != "SUCCESS":

            print(
                "\n❌ Pipeline stopped:"
                " Analysis failed."
            )

            return {
                "status": "FAILED",
                "failed_agent":
                    AnalysisAgent.__name__,
                "error":
                    analysis_result.get("error"),
                "simulation":
                    simulation_result,
                "cleaning":
                    cleaning_result,
                "analysis":
                    analysis_result,
            }

        print("✅ Analysis completed.")

        # ========================================================
        # 4. ALERT DETECTION
        # ========================================================

        print("\n[4/5] ALERT DETECTION AGENT")

        alert_result = self._run_agent(
            workflow_name="MONITORING",
            agent_name=AlertDetectionAgent.__name__,
            agent=AlertDetectionAgent(
                self.session
            ),
            start_time=window_start,
        )

        if alert_result["status"] != "SUCCESS":

            print(
                "\n❌ Pipeline stopped:"
                " Alert Detection failed."
            )

            return {
                "status": "FAILED",
                "failed_agent":
                    AlertDetectionAgent.__name__,
                "error":
                    alert_result.get("error"),
                "simulation":
                    simulation_result,
                "cleaning":
                    cleaning_result,
                "analysis":
                    analysis_result,
                "alert":
                    alert_result,
            }

        print("✅ Alert Detection completed.")

        # ========================================================
        # 5. RECOMMENDATION
        # ========================================================

        print("\n[5/5] RECOMMENDATION AGENT")

        recommendation_result = self._run_agent(
            workflow_name="MONITORING",
            agent_name=RecommendationAgent.__name__,
            agent=RecommendationAgent(
                self.session
            ),
            start_time=window_start,
        )

        if recommendation_result["status"] != "SUCCESS":

            print(
                "\n❌ Pipeline stopped:"
                " Recommendation failed."
            )

            return {
                "status": "FAILED",
                "failed_agent":
                    RecommendationAgent.__name__,
                "error":
                    recommendation_result.get("error"),
                "simulation":
                    simulation_result,
                "cleaning":
                    cleaning_result,
                "analysis":
                    analysis_result,
                "alert":
                    alert_result,
                "recommendation":
                    recommendation_result,
            }

        print("✅ Recommendation completed.")

        # ========================================================
        # COMPLETE
        # ========================================================

        print("\n" + "=" * 70)
        print("🎉 FULL MONITORING PIPELINE COMPLETE")
        print("=" * 70)

        return {
            "status": "SUCCESS",
            "simulation":
                simulation_result,
            "cleaning":
                cleaning_result,
            "analysis":
                analysis_result,
            "alert":
                alert_result,
            "recommendation":
                recommendation_result,
        }
